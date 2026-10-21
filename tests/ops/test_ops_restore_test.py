"""deploy/restore_test.sh: the monthly restore test and its protocol line."""

import re
import stat

import pytest

from tests.ops.helpers import (
    decrypt_backup,
    encrypt_as_backup,
    flip_byte,
    restore_test_databases,
    scalar,
    write_manifest,
)

LINE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) file=(?P<file>\S+) "
    r"result=(?P<result>OK|FAIL) users=(?P<users>\S+) animals=(?P<animals>\S+) "
    r"sources=(?P<sources>\S+) note=(?P<note>.*)$"
)


def protocol(workspace) -> list[re.Match[str]]:
    """The lines of the protocol file, each parsed (a line that does not parse fails)."""
    lines = workspace.log_file.read_text().splitlines()
    parsed = [LINE.match(line) for line in lines]
    assert all(parsed), lines
    return parsed


def manifest_of(backup):
    return backup.with_name(backup.name + ".sha256")


def test_restore_test_writes_an_ok_line_and_cleans_up(workspace, golden_backup, source_db, conn):
    backup = workspace.install_copy_of(golden_backup)
    before = restore_test_databases(conn)

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 0, result.stderr
    (line,) = protocol(workspace)
    assert line["result"] == "OK"
    assert line["file"] == backup.name
    for key, table in (
        ("users", "accounts_user"),
        ("animals", "animals_animal"),
        ("sources", "catalog_scientificsource"),
    ):
        assert line[key] == scalar(conn, source_db, f"SELECT count(*) FROM {table};")
    assert line["note"] == "tables present, counts equal the manifest"
    assert result.stdout.strip() == workspace.log_file.read_text().strip()
    assert stat.S_IMODE(workspace.log_file.stat().st_mode) == 0o600
    assert re.search(r"barf_restore_test_\d{8}t\d{6}z", result.stderr)
    assert restore_test_databases(conn) == before, "the scratch database was not dropped"
    assert {path.name for path in workspace.backup_dir.iterdir()} == {
        backup.name,
        backup.name + ".sha256",
    }, "the test must not leave files in the backup directory"


def test_restore_test_appends_a_line_to_the_protocol_each_time(workspace, golden_backup, source_db):
    workspace.install_copy_of(golden_backup)

    first = workspace.run("restore_test.sh", database=source_db)
    second = workspace.run("restore_test.sh", database=source_db)

    assert first.returncode == second.returncode == 0
    assert [line["result"] for line in protocol(workspace)] == ["OK", "OK"]


def test_restore_test_takes_the_newest_backup_and_ignores_other_files(
    workspace, golden_backup, source_db
):
    workspace.install_copy_of(golden_backup)
    fresh = workspace.make_backup(source_db)
    assert fresh.name > golden_backup.name
    for decoy in ("barf-20991231T235959Z.dump.gpg.bak", "barf-2099.dump.gpg", "README"):
        (workspace.backup_dir / decoy).write_text("not a backup")

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 0, result.stderr
    (line,) = protocol(workspace)
    assert line["file"] == fresh.name


@pytest.mark.parametrize("damage", ["flip-bytes", "truncate-and-rehash", "garbage-archive"])
def test_restore_test_fails_for_a_corrupted_backup(
    workspace, golden_backup, source_db, conn, damage
):
    backup = workspace.install_copy_of(golden_backup)
    if damage == "flip-bytes":
        flip_byte(backup, backup.stat().st_size // 2)
    elif damage == "truncate-and-rehash":
        backup.write_bytes(backup.read_bytes()[: backup.stat().st_size // 2])
        write_manifest(backup)
    else:
        plain = decrypt_backup(workspace, backup)
        backup.unlink()
        manifest_of(backup).unlink()
        backup = encrypt_as_backup(workspace, plain[: len(plain) * 6 // 10], backup.name)
    before = restore_test_databases(conn)

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 1
    (line,) = protocol(workspace)
    assert line["result"] == "FAIL"
    assert line["file"] == backup.name
    assert (line["users"], line["animals"], line["sources"]) == ("-", "-", "-")
    assert "restore into" in line["note"]
    assert restore_test_databases(conn) == before, "the scratch database was not dropped"


def test_restore_test_fails_when_the_counts_differ_from_the_manifest(
    workspace, golden_backup, source_db, conn
):
    backup = workspace.install_copy_of(golden_backup)
    manifest = manifest_of(backup)
    manifest.write_text(re.sub(r"(# count\.animals_animal=)\d+", r"\g<1>99", manifest.read_text()))

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 1
    (line,) = protocol(workspace)
    assert line["result"] == "FAIL"
    assert line["note"].startswith("counts differ from the manifest")
    assert "animals 2 != 99" in line["note"]
    assert line["animals"] == "2"
    assert restore_test_databases(conn) == set()


def test_restore_test_fails_when_the_table_list_differs_from_the_manifest(
    workspace, golden_backup, source_db
):
    backup = workspace.install_copy_of(golden_backup)
    manifest = manifest_of(backup)
    manifest.write_text(re.sub(r"(# tables=.*)", r"\1,ghost_table", manifest.read_text()))

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 1
    assert protocol(workspace)[0]["note"] == "the table list differs from the manifest"


def test_restore_test_only_reports_counts_the_manifest_does_not_record(
    workspace, golden_backup, source_db
):
    backup = workspace.install_copy_of(golden_backup)
    manifest = manifest_of(backup)
    manifest.write_text(
        "".join(
            line
            for line in manifest.read_text().splitlines(keepends=True)
            if not line.startswith(("# count.", "# tables="))
        )
    )

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 0, result.stderr
    (line,) = protocol(workspace)
    assert line["result"] == "OK"
    assert line["users"] != "-"
    assert "only reported" in line["note"]


def test_restore_test_fails_when_application_tables_are_missing(workspace, scratch_db, conn):
    toy = scratch_db()
    scalar(conn, toy, "CREATE TABLE toy (id integer PRIMARY KEY); INSERT INTO toy VALUES (1);")
    workspace.make_backup(toy)

    result = workspace.run("restore_test.sh", database=toy)

    assert result.returncode == 1
    (line,) = protocol(workspace)
    assert line["result"] == "FAIL"
    assert line["note"].startswith("missing tables: ")
    assert "accounts_user" in line["note"]
    assert restore_test_databases(conn) == set()


def test_restore_test_fails_without_any_backup(workspace, source_db):
    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 1
    (line,) = protocol(workspace)
    assert (line["result"], line["file"]) == ("FAIL", "-")
    assert "no backup" in line["note"]


def test_restore_test_fails_with_the_wrong_passphrase(workspace, golden_backup, source_db):
    workspace.install_copy_of(golden_backup)
    workspace.passphrase_file.write_text("a-different-passphrase-of-good-length\n")

    result = workspace.run("restore_test.sh", database=source_db)

    assert result.returncode == 1
    assert protocol(workspace)[0]["result"] == "FAIL"


@pytest.mark.parametrize(
    "variable", ["POSTGRES_DB", "BACKUP_DIR", "BACKUP_PASSPHRASE_FILE", "RESTORE_TEST_LOG"]
)
def test_restore_test_refuses_when_a_required_variable_is_missing(
    workspace, golden_backup, source_db, variable
):
    workspace.install_copy_of(golden_backup)

    result = workspace.run("restore_test.sh", database=source_db, **{variable: None})

    assert result.returncode == 2
    assert variable in result.stderr
    assert not workspace.log_file.exists()


def test_restore_test_refuses_an_unusable_protocol_path(workspace, golden_backup, source_db):
    workspace.install_copy_of(golden_backup)
    link = workspace.root / "link.log"
    link.symlink_to(workspace.root / "elsewhere.log")

    cases = {
        "relative": "protocol.log",
        "missing-directory": str(workspace.root / "nope" / "protocol.log"),
        "symbolic-link": str(link),
    }
    for result in (
        workspace.run("restore_test.sh", database=source_db, RESTORE_TEST_LOG=path)
        for path in cases.values()
    ):
        assert result.returncode == 2, result.stderr
    assert not (workspace.root / "elsewhere.log").exists()
