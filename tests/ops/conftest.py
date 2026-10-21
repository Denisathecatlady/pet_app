"""Fixtures of the tests of the backup scripts (``deploy/``).

The tests skip only when gpg, pg_dump, pg_restore or psql is not installed. A PostgreSQL
server that cannot be reached is an error, as for the Django tests. Every scratch database,
temporary directory and gpg-agent is removed again in finalizers.
"""

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from tests.ops.helpers import (
    PASSPHRASE,
    SCRATCH_PREFIX,
    Workspace,
    connection,
    create_database,
    drop_database,
    missing_tools,
    restore_test_databases,
    seed_django_database,
)


@pytest.fixture(autouse=True)
def _require_tools():
    missing = missing_tools()
    if missing:
        pytest.skip(f"the ops tests need {', '.join(missing)} on PATH (not installed)")


@pytest.fixture(scope="session")
def conn() -> dict[str, str]:
    """Connection settings of the local PostgreSQL server (role with CREATEDB)."""
    return connection()


@pytest.fixture(scope="session")
def gnupghome(request: pytest.FixtureRequest) -> str:
    """A private, short GNUPGHOME (agent socket paths are length limited) for all tests."""
    home = tempfile.mkdtemp(prefix="gh")

    def finalize() -> None:
        subprocess.run(
            ["gpgconf", "--homedir", home, "--kill", "gpg-agent"],
            capture_output=True,
            check=False,
            timeout=60,
        )
        shutil.rmtree(home, ignore_errors=True)

    request.addfinalizer(finalize)
    return home


def _database_factory(request: pytest.FixtureRequest, conn: dict[str, str]) -> Callable[..., str]:
    """Factory of empty scratch databases; the finalizer drops every database it made."""
    created: list[str] = []

    def finalize() -> None:
        for name in created:
            drop_database(conn, name)

    request.addfinalizer(finalize)

    def make(*, create: bool = True) -> str:
        """Name of a new scratch database; ``create=False`` only reserves the name."""
        name = f"{SCRATCH_PREFIX}{uuid.uuid4().hex[:12]}"
        created.append(name)
        if create:
            create_database(conn, name)
        return name

    return make


@pytest.fixture(scope="session")
def session_databases(request: pytest.FixtureRequest, conn: dict[str, str]) -> Callable[..., str]:
    """Scratch databases that live until the end of the session."""
    return _database_factory(request, conn)


@pytest.fixture
def scratch_db(request: pytest.FixtureRequest, conn: dict[str, str]) -> Callable[..., str]:
    """Scratch databases that live for one test."""
    return _database_factory(request, conn)


@pytest.fixture(scope="session")
def source_db(conn: dict[str, str], session_databases: Callable[..., str], gnupghome: str) -> str:
    """Scratch database with the real application schema and a few rows (read-only for tests)."""
    name = session_databases()
    seed_django_database(conn, name, {"PATH": os.environ["PATH"], "GNUPGHOME": gnupghome})
    return name


def _workspace(root: Path, conn: dict[str, str], gnupghome: str, path: str) -> Workspace:
    backup_dir = root / "backups"
    backup_dir.mkdir(mode=0o700)
    backup_dir.chmod(0o700)
    passphrase_file = root / "passphrase"
    passphrase_file.write_text(PASSPHRASE + "\n")
    passphrase_file.chmod(0o600)
    return Workspace(
        root=root,
        backup_dir=backup_dir,
        passphrase_file=passphrase_file,
        log_file=root / "restore-test.log",
        conn=conn,
        gnupghome=gnupghome,
        path=path,
    )


@pytest.fixture
def workspace(tmp_path: Path, conn: dict[str, str], gnupghome: str) -> Workspace:
    """Temporary BACKUP_DIR (mode 700), passphrase file (mode 600) and protocol file path."""
    root = tmp_path / "ws"
    root.mkdir(mode=0o700)
    return _workspace(root, conn, gnupghome, os.environ["PATH"])


@pytest.fixture(scope="session")
def golden_backup(
    tmp_path_factory: pytest.TempPathFactory,
    conn: dict[str, str],
    gnupghome: str,
    source_db: str,
) -> Path:
    """One backup of ``source_db`` made once; tests copy it before they change anything."""
    root = tmp_path_factory.mktemp("golden") / "ws"
    root.mkdir(mode=0o700)
    golden = _workspace(root, conn, gnupghome, os.environ["PATH"])
    return golden.make_backup(source_db)


@pytest.fixture(autouse=True)
def _no_leftover_restore_test_databases(_require_tools: None, conn: dict[str, str]):
    """restore_test.sh must drop its scratch database; drop strays so one failure stays local."""
    before = restore_test_databases(conn)
    yield
    for name in restore_test_databases(conn) - before:
        drop_database(conn, name)
