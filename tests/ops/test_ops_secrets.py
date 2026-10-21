"""No secret on a command line: the arguments of every program the scripts start are recorded.

Thin wrappers named ``pg_dump``, ``psql``, ``pg_restore`` and ``gpg`` are put first on PATH. They
append their argument list to a file and then run the real program. The password and the
passphrase would show up in ``ps`` if the scripts passed them as arguments.
"""

import os
import shutil
from pathlib import Path

from tests.ops.helpers import PASSPHRASE

WRAPPED = ("pg_dump", "psql", "pg_restore", "gpg")
SEPARATOR = "\x1f"


def install_wrappers(directory: Path) -> None:
    directory.mkdir()
    for tool in WRAPPED:
        real = shutil.which(tool)
        wrapper = directory / tool
        # One write per call: wrappers of a pipeline (pg_dump | gpg) run at the same time.
        wrapper.write_text(
            "#!/bin/sh\n"
            "sep=$(printf '\\037')\n"
            f'line="{tool}"\n'
            'for a in "$@"; do line="$line$sep$a"; done\n'
            'printf \'%s\\n\' "$line" >> "$ARGV_LOG"\n'
            f'exec "{real}" "$@"\n'
        )
        wrapper.chmod(0o755)


def recorded_commands(log: Path) -> list[list[str]]:
    return [line.split(SEPARATOR) for line in log.read_text().splitlines()]


def test_no_script_puts_a_password_or_passphrase_on_a_command_line(
    workspace, source_db, scratch_db, conn
):
    wrappers = workspace.root / "wrappers"
    install_wrappers(wrappers)
    log = workspace.root / "argv.log"
    extra = {"PATH": f"{wrappers}:{os.environ['PATH']}", "ARGV_LOG": str(log)}

    backup = workspace.run("backup_db.sh", database=source_db, **extra)
    assert backup.returncode == 0, backup.stderr
    target = scratch_db(create=False)
    restore = workspace.run(
        "restore_db.sh",
        "--create",
        backup.stdout.strip(),
        database=source_db,
        RESTORE_TARGET_DB=target,
        **extra,
    )
    assert restore.returncode == 0, restore.stderr
    test = workspace.run("restore_test.sh", database=source_db, **extra)
    assert test.returncode == 0, test.stderr

    commands = recorded_commands(log)
    assert {command[0] for command in commands} == set(WRAPPED)
    password = conn["POSTGRES_PASSWORD"]
    for command in commands:
        for argument in command[1:]:
            assert PASSPHRASE not in argument, command[0]
            assert argument != password, (command[0], argument)
            assert not argument.endswith((f"={password}", f":{password}")), (command[0], argument)
            assert not argument.startswith("--password"), (command[0], argument)
            assert argument not in {"-W", "--passphrase", "-p"}, (command[0], argument)
    gpg_calls = [command for command in commands if command[0] == "gpg"]
    assert gpg_calls
    for command in gpg_calls:
        assert "--batch" in command
        assert "--passphrase-file" in command
        assert command[command.index("--passphrase-file") + 1] == str(workspace.passphrase_file)
    encrypt = [command for command in gpg_calls if "--symmetric" in command]
    assert encrypt
    assert all("AES256" in command for command in encrypt)
    assert any(command[0] == "pg_dump" and "--format=custom" in command for command in commands)
    assert any(
        command[0] == "pg_restore" and {"--no-owner", "--no-privileges"} <= set(command)
        for command in commands
    )
