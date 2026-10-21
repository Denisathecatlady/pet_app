"""deploy/backup_db.sh: encrypted dump, manifest, refusals and the environment file."""

import hashlib
import re
import stat
import subprocess
from pathlib import Path

import pytest

from tests.ops.helpers import (
    CZECH_ANIMAL_NAME,
    OWNER_EMAIL,
    PASSPHRASE,
    Workspace,
    decrypt_backup,
    scalar,
)

BACKUP_NAME = re.compile(r"^barf-\d{8}T\d{6}Z\.dump\.gpg$")
REQUIRED = ["POSTGRES_DB", "POSTGRES_USER", "POSTGRES_HOST", "BACKUP_DIR", "BACKUP_PASSPHRASE_FILE"]


def mode_of(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_backup_writes_exactly_one_encrypted_file_and_one_manifest(workspace, source_db, conn):
    result = workspace.run("backup_db.sh", database=source_db)

    assert result.returncode == 0, result.stderr
    names = sorted(path.name for path in workspace.backup_dir.iterdir())
    assert len(names) == 2
    dump_name, manifest_name = names
    assert BACKUP_NAME.match(dump_name)
    assert manifest_name == dump_name + ".sha256"
    dump = workspace.backup_dir / dump_name
    assert result.stdout.strip() == str(dump)
    assert mode_of(dump) == 0o600
    assert mode_of(workspace.backup_dir / manifest_name) == 0o600

    manifest = (workspace.backup_dir / manifest_name).read_text().splitlines()
    assert f"{hashlib.sha256(dump.read_bytes()).hexdigest()}  {dump_name}" in manifest
    checked = subprocess.run(
        ["sha256sum", "--check", "--strict", manifest_name],
        cwd=workspace.backup_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    for table, key in (
        ("accounts_user", "users"),
        ("animals_animal", "animals"),
        ("catalog_scientificsource", "sources"),
    ):
        live = scalar(conn, source_db, f"SELECT count(*) FROM {table};")
        assert f"# count.{table}={live}" in manifest, key
    assert int(live) > 0
    assert any(line.startswith("# tables=") and "accounts_user" in line for line in manifest)


def test_backup_is_not_a_readable_dump_without_decryption(golden_backup, workspace):
    data = golden_backup.read_bytes()

    assert not data.startswith(b"PGDMP")
    for secret in (OWNER_EMAIL, CZECH_ANIMAL_NAME, "accounts_user", "ScientificSource"):
        assert secret.encode() not in data
    listing = subprocess.run(
        ["pg_restore", "--list", str(golden_backup)], capture_output=True, text=True, check=False
    )
    assert listing.returncode != 0
    packets = subprocess.run(
        ["gpg", "--list-packets", str(golden_backup)],
        env=workspace.env(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert "symkey enc packet" in packets.stdout + packets.stderr
    assert "cipher 9" in packets.stdout + packets.stderr, "AES256 expected"
    assert decrypt_backup(workspace, golden_backup).startswith(b"PGDMP")


@pytest.mark.parametrize("variable", REQUIRED)
def test_backup_refuses_when_a_required_variable_is_missing(workspace, source_db, variable):
    result = workspace.run("backup_db.sh", database=source_db, **{variable: None})

    assert result.returncode == 2
    assert variable in result.stderr
    assert result.stdout == ""
    assert list(workspace.backup_dir.iterdir()) == []


def test_backup_refuses_without_any_password_source(workspace, source_db):
    result = workspace.run("backup_db.sh", database=source_db, POSTGRES_PASSWORD=None)

    assert result.returncode == 2
    assert "POSTGRES_PASSWORD" in result.stderr
    assert list(workspace.backup_dir.iterdir()) == []


def test_backup_accepts_the_password_from_a_pgpass_file(workspace, source_db, conn):
    pgpass = workspace.root / "pgpass"
    pgpass.write_text(
        f"{conn['POSTGRES_HOST']}:{conn['POSTGRES_PORT']}:*:"
        f"{conn['POSTGRES_USER']}:{conn['POSTGRES_PASSWORD']}\n"
    )
    pgpass.chmod(0o600)

    result = workspace.run(
        "backup_db.sh", database=source_db, POSTGRES_PASSWORD=None, PGPASSFILE=str(pgpass)
    )

    assert result.returncode == 0, result.stderr
    assert len(workspace.backups()) == 1


def test_the_password_comes_from_pgpassfile_then_postgres_password_then_pgpassword(
    workspace, source_db, conn
):
    pgpass = workspace.root / "pgpass"
    pgpass.write_text(
        f"{conn['POSTGRES_HOST']}:{conn['POSTGRES_PORT']}:*:"
        f"{conn['POSTGRES_USER']}:{conn['POSTGRES_PASSWORD']}\n"
    )
    pgpass.chmod(0o600)
    wrong = "an-inherited-wrong-password"
    cases = {
        # The file wins over both variables.
        "pgpassfile": {"PGPASSFILE": str(pgpass), "POSTGRES_PASSWORD": wrong, "PGPASSWORD": wrong},
        # POSTGRES_PASSWORD (as in the Django settings) wins over an inherited PGPASSWORD.
        "postgres-password": {"PGPASSWORD": wrong},
        # An inherited PGPASSWORD is used when nothing else is configured.
        "pgpassword": {"POSTGRES_PASSWORD": None, "PGPASSWORD": conn["POSTGRES_PASSWORD"]},
    }
    for name, overrides in cases.items():
        result = workspace.run("backup_db.sh", database=source_db, **overrides)
        assert result.returncode == 0, (name, result.stderr)
        for path in workspace.backup_dir.glob("barf-*"):
            path.unlink()


def test_backup_refuses_a_pgpass_file_others_can_read(workspace, source_db, conn):
    pgpass = workspace.root / "pgpass"
    pgpass.write_text("*:*:*:*:secret\n")
    pgpass.chmod(0o644)

    result = workspace.run(
        "backup_db.sh", database=source_db, POSTGRES_PASSWORD=None, PGPASSFILE=str(pgpass)
    )

    assert result.returncode == 2
    assert "PGPASSFILE" in result.stderr


@pytest.mark.parametrize("mode", [0o755, 0o705, 0o701, 0o777, 0o744])
def test_backup_refuses_a_backup_dir_others_can_access(workspace, source_db, mode):
    workspace.backup_dir.chmod(mode)

    result = workspace.run("backup_db.sh", database=source_db)

    assert result.returncode == 2
    assert "accessible to other users" in result.stderr
    assert list(workspace.backup_dir.iterdir()) == []


def test_backup_accepts_a_group_readable_backup_dir(workspace, source_db):
    workspace.backup_dir.chmod(0o750)

    result = workspace.run("backup_db.sh", database=source_db)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "location", ["relative/path", "does-not-exist"], ids=["relative", "missing-directory"]
)
def test_backup_refuses_an_unusable_backup_dir(workspace, source_db, location):
    target = location if location.startswith("relative") else str(workspace.root / location)

    result = workspace.run("backup_db.sh", database=source_db, BACKUP_DIR=target)

    assert result.returncode == 2
    assert "BACKUP_DIR" in result.stderr


def test_backup_refuses_a_passphrase_file_others_can_read(workspace, source_db):
    workspace.passphrase_file.chmod(0o644)

    result = workspace.run("backup_db.sh", database=source_db)

    assert result.returncode == 2
    assert "BACKUP_PASSPHRASE_FILE" in result.stderr
    assert PASSPHRASE not in result.stderr
    assert list(workspace.backup_dir.iterdir()) == []


def test_backup_refuses_a_short_passphrase(workspace, source_db):
    workspace.passphrase_file.write_text("too-short\n")

    result = workspace.run("backup_db.sh", database=source_db)

    assert result.returncode == 2
    assert "at least" in result.stderr
    assert "too-short" not in result.stderr


@pytest.mark.parametrize(
    ("database", "overrides"),
    [
        ("barf_ops_test_does_not_exist", {}),
        (None, {"POSTGRES_PASSWORD": "definitely-wrong"}),
        ("bad name; DROP DATABASE x", {}),
    ],
    ids=["missing-database", "wrong-password", "invalid-name"],
)
def test_backup_failure_exits_non_zero_and_leaves_nothing_behind(
    workspace, source_db, database, overrides
):
    result = workspace.run("backup_db.sh", database=database or source_db, **overrides)

    assert result.returncode != 0
    assert result.stdout == ""
    assert list(workspace.backup_dir.iterdir()) == []


def test_backup_rejects_arguments(workspace, source_db):
    assert workspace.run("backup_db.sh", "--nonsense", database=source_db).returncode == 2
    assert workspace.run("backup_db.sh", "--prune-only", "x", database=source_db).returncode == 2


def test_backup_never_leaves_an_unencrypted_file(workspace, source_db):
    workspace.make_backup(source_db)

    for path in workspace.root.rglob("*"):
        if path.is_file() and path != workspace.passphrase_file:
            assert not path.read_bytes().startswith(b"PGDMP"), path


# --- environment file -----------------------------------------------------------------------


def env_file_text(workspace: Workspace, database: str, **extra: str) -> str:
    values = {
        "POSTGRES_DB": database,
        "POSTGRES_USER": workspace.conn["POSTGRES_USER"],
        "POSTGRES_HOST": workspace.conn["POSTGRES_HOST"],
        "POSTGRES_PORT": workspace.conn["POSTGRES_PORT"],
        "POSTGRES_PASSWORD": f'"{workspace.conn["POSTGRES_PASSWORD"]}"',
        "BACKUP_DIR": str(workspace.backup_dir),
        "BACKUP_PASSPHRASE_FILE": str(workspace.passphrase_file),
        **extra,
    }
    lines = ["# configuration of the backup scripts", ""]
    lines += [f"{name}={value}" for name, value in values.items()]
    lines += [
        "DJANGO_SECRET_KEY=not-read-by-the-scripts",
        "DJANGO_DEFAULT_FROM_EMAIL='A B <a@b.cz>'",
    ]
    return "\n".join(lines) + "\n"


def test_configuration_can_come_from_a_file_named_by_barf_env_file(workspace, source_db):
    env_file = workspace.root / "ops.env"
    env_file.write_text(env_file_text(workspace, source_db))
    env_file.chmod(0o600)

    result = workspace.run_with_env(
        "backup_db.sh", {**workspace.base_env(), "BARF_ENV_FILE": str(env_file)}
    )

    assert result.returncode == 0, result.stderr
    assert len(workspace.backups()) == 1


def test_the_environment_wins_over_the_env_file(workspace, source_db):
    env_file = workspace.root / "ops.env"
    wrong = workspace.root / "nowhere"
    env_file.write_text(env_file_text(workspace, source_db, BACKUP_DIR=str(wrong)))
    env_file.chmod(0o600)

    result = workspace.run_with_env(
        "backup_db.sh",
        {
            **workspace.base_env(),
            "BARF_ENV_FILE": str(env_file),
            "BACKUP_DIR": str(workspace.backup_dir),
        },
    )

    assert result.returncode == 0, result.stderr
    assert len(workspace.backups()) == 1


def test_an_env_file_others_can_read_is_refused(workspace, source_db):
    env_file = workspace.root / "ops.env"
    env_file.write_text(env_file_text(workspace, source_db))
    env_file.chmod(0o640)

    result = workspace.run_with_env(
        "backup_db.sh", {**workspace.base_env(), "BARF_ENV_FILE": str(env_file)}
    )

    assert result.returncode == 2
    assert "BARF_ENV_FILE" in result.stderr
    assert list(workspace.backup_dir.iterdir()) == []


def test_an_env_file_is_parsed_and_never_executed(workspace, source_db):
    marker = workspace.root / "executed"
    env_file = workspace.root / "ops.env"
    env_file.write_text(
        env_file_text(workspace, source_db, POSTGRES_PORT=f"$(touch {marker})")
        + f"BACKUP_FILE_NOTE=`touch {marker}`\n"
    )
    env_file.chmod(0o600)

    result = workspace.run_with_env(
        "backup_db.sh", {**workspace.base_env(), "BARF_ENV_FILE": str(env_file)}
    )

    assert result.returncode == 2
    assert not marker.exists()


def test_a_malformed_env_file_line_is_refused(workspace, source_db):
    env_file = workspace.root / "ops.env"
    env_file.write_text(env_file_text(workspace, source_db) + "this is not an assignment\n")
    env_file.chmod(0o600)

    result = workspace.run_with_env(
        "backup_db.sh", {**workspace.base_env(), "BARF_ENV_FILE": str(env_file)}
    )

    assert result.returncode == 2
    assert "expected NAME=value" in result.stderr
