"""deploy/restore_db.sh: checksum, refusals, content reproduction, rollback."""

import pytest

from tests.ops.helpers import (
    CZECH_ANIMAL_NAME,
    database_exists,
    decrypt_backup,
    encrypt_as_backup,
    flip_byte,
    scalar,
    table_digests,
    write_manifest,
)

OFFLINE_NAME = "barf-20250102T030405Z.dump.gpg"


def restore(workspace, backup, target, *flags, database):
    """Run restore_db.sh for ``backup`` into ``target`` with POSTGRES_DB=``database``."""
    return workspace.run(
        "restore_db.sh", *flags, str(backup), database=database, RESTORE_TARGET_DB=target
    )


def test_restore_reproduces_the_table_contents(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 0, result.stderr
    restored = table_digests(conn, target)
    assert restored == table_digests(conn, source_db)
    assert len(restored) > 20
    names = scalar(conn, target, "SELECT string_agg(name, ',' ORDER BY name) FROM animals_animal;")
    assert CZECH_ANIMAL_NAME in names.split(",")
    # Objects belong to the restoring role, not to the role that made the dump.
    owners = scalar(
        conn, target, "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname='public';"
    )
    assert owners == conn["POSTGRES_USER"]


def test_restore_into_an_existing_empty_database_needs_no_create_flag(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    target = scratch_db()

    result = restore(workspace, backup, target, database=source_db)

    assert result.returncode == 0, result.stderr
    assert table_digests(conn, target) == table_digests(conn, source_db)


def test_restore_into_a_missing_database_requires_create(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, database=source_db)

    assert result.returncode == 2
    assert "--create" in result.stderr
    assert not database_exists(conn, target)


def test_restore_refuses_the_live_database_without_the_flag(
    workspace, golden_backup, source_db, conn
):
    backup = workspace.install_copy_of(golden_backup)
    before = table_digests(conn, source_db)

    result = restore(workspace, backup, source_db, database=source_db)

    assert result.returncode == 2
    assert "--i-know-this-overwrites-production" in result.stderr
    assert table_digests(conn, source_db) == before


def test_restore_refuses_the_live_database_even_with_create(
    workspace, golden_backup, source_db, conn
):
    backup = workspace.install_copy_of(golden_backup)

    result = restore(workspace, backup, source_db, "--create", database=source_db)

    assert result.returncode == 2
    assert "--i-know-this-overwrites-production" in result.stderr


def test_restore_replaces_the_live_database_with_the_flag(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    live = scratch_db(create=False)
    first = restore(workspace, backup, live, "--create", database=source_db)
    assert first.returncode == 0, first.stderr
    scalar(
        conn, live, "DELETE FROM animals_animal; DELETE FROM catalog_historicalscientificsource;"
    )
    assert table_digests(conn, live) != table_digests(conn, source_db)

    result = restore(workspace, backup, live, "--i-know-this-overwrites-production", database=live)

    assert result.returncode == 0, result.stderr
    assert "WARNING" in result.stderr
    assert table_digests(conn, live) == table_digests(conn, source_db)


def test_a_failed_restore_over_the_live_database_changes_nothing(
    workspace, golden_backup, source_db, conn, scratch_db
):
    # Valid checksum, decryptable, but the archive is cut in the middle of the data.
    plain = decrypt_backup(workspace, golden_backup)
    broken = encrypt_as_backup(workspace, plain[: len(plain) * 6 // 10], OFFLINE_NAME)
    live = scratch_db(create=False)
    good = workspace.install_copy_of(golden_backup)
    assert restore(workspace, good, live, "--create", database=source_db).returncode == 0
    before = table_digests(conn, live)

    result = restore(workspace, broken, live, "--i-know-this-overwrites-production", database=live)

    assert result.returncode == 1
    assert "pg_restore failed" in result.stderr
    assert table_digests(conn, live) == before


def test_a_failed_restore_drops_the_database_this_run_created(
    workspace, golden_backup, source_db, conn, scratch_db
):
    plain = decrypt_backup(workspace, golden_backup)
    broken = encrypt_as_backup(workspace, plain[: len(plain) * 6 // 10], OFFLINE_NAME)
    target = scratch_db(create=False)

    result = restore(workspace, broken, target, "--create", database=source_db)

    assert result.returncode == 1
    assert not database_exists(conn, target)


def test_a_failed_restore_never_drops_a_database_it_did_not_create(
    workspace, golden_backup, source_db, conn, scratch_db
):
    plain = decrypt_backup(workspace, golden_backup)
    broken = encrypt_as_backup(workspace, plain[: len(plain) * 6 // 10], OFFLINE_NAME)
    target = scratch_db()

    result = restore(workspace, broken, target, "--create", database=source_db)

    assert result.returncode == 1
    assert database_exists(conn, target)


def test_restore_fails_on_a_tampered_file_because_of_the_checksum(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    flip_byte(backup, backup.stat().st_size // 2)
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr
    assert not database_exists(conn, target)


@pytest.mark.parametrize("damage", ["flip-middle", "flip-start", "truncate"])
def test_restore_fails_on_a_damaged_file_even_when_the_manifest_matches(
    workspace, golden_backup, source_db, conn, scratch_db, damage
):
    backup = workspace.install_copy_of(golden_backup)
    if damage == "truncate":
        backup.write_bytes(backup.read_bytes()[: backup.stat().st_size // 2])
    else:
        flip_byte(backup, 40 if damage == "flip-start" else backup.stat().st_size // 2)
    write_manifest(backup)
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 1
    assert "cannot decrypt" in result.stderr
    assert not database_exists(conn, target)


def test_restore_fails_when_the_manifest_is_missing(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    backup.with_name(backup.name + ".sha256").unlink()
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 1
    assert "manifest" in result.stderr
    assert not database_exists(conn, target)


def test_restore_fails_when_the_manifest_lists_another_file(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    manifest = backup.with_name(backup.name + ".sha256")
    manifest.write_text(manifest.read_text().replace(backup.name, "barf-20200101T000000Z.dump.gpg"))
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 1
    assert "no checksum line" in result.stderr
    assert not database_exists(conn, target)


def test_restore_fails_with_the_wrong_passphrase(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    workspace.passphrase_file.write_text("a-different-passphrase-of-good-length\n")
    target = scratch_db(create=False)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 1
    assert "cannot decrypt" in result.stderr
    assert not database_exists(conn, target)


def test_restore_refuses_a_non_empty_target(workspace, golden_backup, source_db, conn, scratch_db):
    backup = workspace.install_copy_of(golden_backup)
    target = scratch_db(create=False)
    assert restore(workspace, backup, target, "--create", database=source_db).returncode == 0
    before = table_digests(conn, target)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 2
    assert "not empty" in result.stderr
    assert table_digests(conn, target) == before


def test_restore_touches_only_files_named_like_backups(
    workspace, golden_backup, source_db, scratch_db
):
    copy = workspace.backup_dir / "evil.dump.gpg"
    copy.write_bytes(golden_backup.read_bytes())

    result = restore(workspace, copy, scratch_db(create=False), "--create", database=source_db)

    assert result.returncode == 2
    assert "not named like a backup" in result.stderr


@pytest.mark.parametrize("target", ["bad name", "x=y", "postgresql://h/db", "-oops", ""])
def test_restore_rejects_invalid_database_names(workspace, golden_backup, source_db, target):
    backup = workspace.install_copy_of(golden_backup)

    result = restore(workspace, backup, target, "--create", database=source_db)

    assert result.returncode == 2


def test_restore_usage_errors(workspace, golden_backup, source_db):
    backup = workspace.install_copy_of(golden_backup)

    assert workspace.run("restore_db.sh", database=source_db).returncode == 2
    no_target = workspace.run("restore_db.sh", str(backup), database=source_db)
    assert no_target.returncode == 2
    assert "RESTORE_TARGET_DB" in no_target.stderr
    unknown = restore(workspace, backup, "x", "--force", database=source_db)
    assert unknown.returncode == 2
    assert "unknown option" in unknown.stderr
