"""Stopping a running script (Ctrl-C, ``systemctl stop``): signal to the whole process group.

A slow ``pg_dump`` / ``pg_restore`` wrapper gives the test time to interrupt. After the
interruption nothing may be left: no partial backup file, no half-created database, no open
session. (A signal sent to the script alone is handled by bash only after the running command
ends; that is why the group is signalled, as a terminal or a service manager does.)
"""

import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from tests.ops.helpers import DEPLOY_DIR, database_exists, psql, table_digests

DEADLINE = 60


def slow_wrapper(directory: Path, tool: str) -> None:
    directory.mkdir(exist_ok=True)
    wrapper = directory / tool
    wrapper.write_text(f'#!/bin/sh\nsleep 120\nexec "{shutil.which(tool)}" "$@"\n')
    wrapper.chmod(0o755)


def wait_for(condition, what: str) -> None:
    end = time.monotonic() + DEADLINE
    while time.monotonic() < end:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def start_in_own_group(script: str, *args: str, env: dict[str, str]):
    return subprocess.Popen(
        [str(DEPLOY_DIR / script), *args],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def sessions_in(conn, database: str) -> str:
    return psql(
        conn, "postgres", f"SELECT count(*) FROM pg_stat_activity WHERE datname = '{database}';"
    )


def test_interrupting_a_backup_leaves_no_file_and_no_session(workspace, source_db, conn):
    wrappers = workspace.root / "wrappers"
    slow_wrapper(wrappers, "pg_dump")
    env = workspace.env(source_db, PATH=f"{wrappers}:{os.environ['PATH']}")
    process = start_in_own_group("backup_db.sh", env=env)
    try:
        wait_for(lambda: any(workspace.backup_dir.glob(".barf-partial.*")), "the dump to start")
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=DEADLINE)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()

    assert process.returncode != 0
    assert list(workspace.backup_dir.iterdir()) == []
    wait_for(lambda: sessions_in(conn, source_db) == "0", "the snapshot session to close")


def test_interrupting_a_restore_leaves_no_database_behind(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    wrappers = workspace.root / "wrappers"
    slow_wrapper(wrappers, "pg_restore")
    target = scratch_db(create=False)
    env = workspace.env(
        source_db, RESTORE_TARGET_DB=target, PATH=f"{wrappers}:{os.environ['PATH']}"
    )
    process = start_in_own_group("restore_db.sh", "--create", str(backup), env=env)
    try:
        wait_for(lambda: database_exists(conn, target), "the target database to be created")
        time.sleep(0.5)
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=DEADLINE)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()

    assert process.returncode != 0
    assert not database_exists(conn, target)


def test_interrupting_a_restore_over_the_live_database_changes_nothing(
    workspace, golden_backup, source_db, conn, scratch_db
):
    backup = workspace.install_copy_of(golden_backup)
    live = scratch_db(create=False)
    first = workspace.run(
        "restore_db.sh", "--create", str(backup), database=source_db, RESTORE_TARGET_DB=live
    )
    assert first.returncode == 0, first.stderr
    before = table_digests(conn, live)
    wrappers = workspace.root / "wrappers"
    slow_wrapper(wrappers, "pg_restore")
    env = workspace.env(live, RESTORE_TARGET_DB=live, PATH=f"{wrappers}:{os.environ['PATH']}")
    process = start_in_own_group(
        "restore_db.sh", "--i-know-this-overwrites-production", str(backup), env=env
    )
    try:
        time.sleep(4)  # decryption check done, pg_restore wrapper sleeping (either way: no change)
        os.killpg(process.pid, signal.SIGTERM)
        process.communicate(timeout=DEADLINE)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()

    assert process.returncode != 0
    assert table_digests(conn, live) == before
