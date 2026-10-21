"""Helpers of the tests of the backup scripts in ``deploy/`` (no Django ORM, no ``db`` fixture).

The tests talk to PostgreSQL only through ``psql`` and the scripts under test, and only with
scratch databases whose names start with ``SCRATCH_PREFIX`` (or ``barf_restore_test_``, which
``restore_test.sh`` creates itself). The databases ``barf`` and ``test_barf`` are never touched.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from config.settings.dev import LOCAL_DATABASE_DEFAULTS

REPO_DIR = Path(__file__).resolve().parents[2]
DEPLOY_DIR = REPO_DIR / "deploy"
BACKEND_DIR = REPO_DIR / "backend"

SCRATCH_PREFIX = "barf_ops_test_"
RESTORE_TEST_PREFIX = "barf_restore_test_"
PROTECTED_DATABASES = frozenset({"barf", "test_barf", "postgres", "template0", "template1"})
REQUIRED_TOOLS = ("gpg", "pg_dump", "pg_restore", "psql")

PASSPHRASE = "ops-test-passphrase-0123456789abcdef"
OTHER_PASSPHRASE = "another-test-passphrase-9876543210zyx"
OWNER_EMAIL = "ops-owner@example.cz"
CZECH_ANIMAL_NAME = "Měsíček"

SEED_CODE = f"""
from accounts.models import User
from animals.models import ActivityLevel, Animal, Sex, Species
owner = User.objects.create_user(email={OWNER_EMAIL!r}, password="Kopretina-Rybnik-2026")
Animal.objects.create(owner=owner, name="Rex", species=Species.DOG, sex=Sex.MALE,
                      activity_level=ActivityLevel.MODERATE)
Animal.objects.create(owner=owner, name={CZECH_ANIMAL_NAME!r}, species=Species.CAT,
                      sex=Sex.FEMALE, activity_level=ActivityLevel.MODERATE)
"""


def connection() -> dict[str, str]:
    """POSTGRES_* of the local test server (environment first, development defaults second)."""
    return {
        name: os.environ.get(name) or default for name, default in LOCAL_DATABASE_DEFAULTS.items()
    }


def missing_tools() -> list[str]:
    """Names of the programs the tests need that are not on PATH."""
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def _psql_command(conn: dict[str, str], database: str) -> list[str]:
    return [
        "psql",
        "--no-psqlrc",
        "--no-password",
        "--quiet",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
        f"--host={conn['POSTGRES_HOST']}",
        f"--port={conn['POSTGRES_PORT']}",
        f"--username={conn['POSTGRES_USER']}",
        f"--dbname={database}",
    ]


def psql(conn: dict[str, str], database: str, sql: str) -> str:
    """Run ``sql`` in ``database`` and return stdout; raises on any error."""
    result = subprocess.run(
        _psql_command(conn, database),
        input=sql,
        env={"PATH": os.environ["PATH"], "PGPASSWORD": conn["POSTGRES_PASSWORD"]},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"psql failed in {database}: {result.stderr}")
    return result.stdout.strip()


def _assert_disposable(name: str) -> None:
    allowed = name.startswith((SCRATCH_PREFIX, RESTORE_TEST_PREFIX))
    if not allowed or name in PROTECTED_DATABASES:
        raise AssertionError(f"refusing to touch the database {name!r}")


def create_database(conn: dict[str, str], name: str) -> None:
    """Create the empty scratch database ``name`` through the maintenance database."""
    _assert_disposable(name)
    psql(conn, "postgres", f"CREATE DATABASE \"{name}\" TEMPLATE template0 ENCODING 'UTF8';")


def drop_database(conn: dict[str, str], name: str) -> None:
    """Drop the scratch database ``name`` (no error when it does not exist)."""
    _assert_disposable(name)
    psql(conn, "postgres", f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE);')


def database_exists(conn: dict[str, str], name: str) -> bool:
    found = psql(conn, "postgres", f"SELECT count(*) FROM pg_database WHERE datname = '{name}';")
    return found == "1"


def restore_test_databases(conn: dict[str, str]) -> set[str]:
    """Names of the databases created by ``restore_test.sh`` that exist right now."""
    names = psql(
        conn,
        "postgres",
        f"SELECT datname FROM pg_database WHERE datname LIKE '{RESTORE_TEST_PREFIX}%';",
    )
    return set(names.split())


def table_digests(conn: dict[str, str], database: str) -> dict[str, str]:
    """MD5 over the text of all rows of every table in ``public`` (content, not statistics)."""
    tables = psql(
        conn,
        database,
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;",
    ).split()
    statements = "\n".join(
        f"SELECT md5(coalesce(string_agg(t::text, E'\\n' ORDER BY t::text), '')) "
        f'FROM public."{table}" AS t;'
        for table in tables
    )
    digests = psql(conn, database, statements).split()
    assert len(digests) == len(tables)
    return dict(zip(tables, digests, strict=True))


def scalar(conn: dict[str, str], database: str, sql: str) -> str:
    return psql(conn, database, sql)


def seed_django_database(conn: dict[str, str], name: str, base_env: dict[str, str]) -> None:
    """Create the real schema in the scratch database ``name`` and add a few rows."""
    _assert_disposable(name)
    env = {
        **base_env,
        **conn,
        "POSTGRES_DB": name,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
    }
    for command in (
        ["migrate", "--noinput", "--verbosity", "0"],
        ["shell", "--command", SEED_CODE],
    ):
        result = subprocess.run(
            [sys.executable, "manage.py", *command],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if result.returncode != 0:
            raise AssertionError(f"manage.py {command[0]} failed: {result.stderr[-2000:]}")


@dataclass
class Workspace:
    """A temporary BACKUP_DIR (mode 700), passphrase file (mode 600) and protocol file path."""

    root: Path
    backup_dir: Path
    passphrase_file: Path
    log_file: Path
    conn: dict[str, str]
    gnupghome: str
    path: str

    def base_env(self) -> dict[str, str]:
        """Only what every program needs: no database, backup or password variable."""
        return {
            "PATH": self.path,
            "HOME": str(self.root),
            "LANG": "C",
            "GNUPGHOME": self.gnupghome,
        }

    def env(self, database: str | None = None, **overrides: str | None) -> dict[str, str]:
        """Environment of a script run; an override of ``None`` removes the variable."""
        env: dict[str, str | None] = {
            **self.base_env(),
            **self.conn,
            "BACKUP_DIR": str(self.backup_dir),
            "BACKUP_PASSPHRASE_FILE": str(self.passphrase_file),
            "RESTORE_TEST_LOG": str(self.log_file),
        }
        if database is not None:
            env["POSTGRES_DB"] = database
        env.update(overrides)
        return {key: value for key, value in env.items() if value is not None}

    def run(
        self, script: str, *args: str, database: str | None = None, **overrides: str | None
    ) -> subprocess.CompletedProcess[str]:
        """Run ``deploy/<script>`` with this workspace's environment."""
        return self.run_with_env(script, self.env(database, **overrides), *args)

    def run_with_env(
        self, script: str, env: dict[str, str], *args: str
    ) -> subprocess.CompletedProcess[str]:
        """Run ``deploy/<script>`` with exactly ``env`` as its environment."""
        return subprocess.run(
            [str(DEPLOY_DIR / script), *args],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

    def backups(self) -> list[Path]:
        """The ``.dump.gpg`` files in the backup directory, oldest first."""
        return sorted(self.backup_dir.glob("barf-*.dump.gpg"))

    def make_backup(self, database: str) -> Path:
        """Run ``backup_db.sh`` for ``database``; return the new backup file."""
        before = set(self.backups())
        result = self.run("backup_db.sh", database=database)
        assert result.returncode == 0, result.stderr
        new = set(self.backups()) - before
        assert len(new) == 1, result.stderr
        return new.pop()

    def install_copy_of(self, backup: Path) -> Path:
        """Copy a backup and its manifest into this workspace's backup directory."""
        target = self.backup_dir / backup.name
        shutil.copy2(backup, target)
        shutil.copy2(
            backup.with_name(backup.name + ".sha256"), target.with_name(backup.name + ".sha256")
        )
        return target


def gpg_command(workspace: Workspace, *args: str) -> list[str]:
    """``gpg`` in batch mode with the passphrase file of ``workspace``."""
    return [
        "gpg",
        "--batch",
        "--no-tty",
        "--quiet",
        "--pinentry-mode",
        "loopback",
        "--passphrase-file",
        str(workspace.passphrase_file),
        *args,
    ]


def decrypt_backup(workspace: Workspace, backup: Path) -> bytes:
    """Plain pg_dump archive inside ``backup`` (decrypted with the workspace passphrase)."""
    result = subprocess.run(
        gpg_command(workspace, "--decrypt", str(backup)),
        env=workspace.env(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def write_manifest(backup: Path) -> None:
    """(Re)write ``<backup>.sha256`` for the current content, without any counts."""
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    backup.with_name(backup.name + ".sha256").write_text(f"{digest}  {backup.name}\n")


def encrypt_as_backup(workspace: Workspace, plain: bytes, name: str) -> Path:
    """Encrypt ``plain`` into ``<backup dir>/<name>`` with a matching manifest."""
    target = workspace.backup_dir / name
    result = subprocess.run(
        gpg_command(workspace, "--symmetric", "--cipher-algo", "AES256", "--output", str(target)),
        input=plain,
        env=workspace.env(),
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    write_manifest(target)
    return target


def flip_byte(path: Path, offset: int) -> None:
    """Change one byte of ``path`` in place."""
    data = bytearray(path.read_bytes())
    data[offset] ^= 0xFF
    path.write_bytes(bytes(data))
