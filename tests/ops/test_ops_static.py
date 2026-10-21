"""Static checks of deploy/: script hygiene, crontab example, documentation of the variables."""

import re
import shutil
import stat
import subprocess

import pytest

from tests.ops.helpers import DEPLOY_DIR, REPO_DIR

SCRIPTS = ["backup_db.sh", "restore_db.sh", "restore_test.sh"]
ALL_SHELL = [*SCRIPTS, "lib.sh"]
GUIDE = REPO_DIR / "docs" / "13-nasazeni-a-provoz.md"

# Variables read by the scripts (the guide must describe every one of them).
SCRIPT_VARIABLES = [
    "BARF_ENV_FILE",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_PASSWORD",
    "POSTGRES_MAINTENANCE_DB",
    "PGPASSFILE",
    "PGPASSWORD",
    "BACKUP_DIR",
    "BACKUP_PASSPHRASE_FILE",
    "RESTORE_TARGET_DB",
    "RESTORE_TEST_LOG",
    "GNUPGHOME",
]


@pytest.mark.parametrize("name", SCRIPTS)
def test_scripts_are_executable_and_start_strict(name):
    path = DEPLOY_DIR / name
    text = path.read_text()

    assert text.startswith("#!/usr/bin/env bash\n")
    assert path.stat().st_mode & stat.S_IXUSR
    assert "\nset -euo pipefail\n" in text
    assert "\numask 077\n" in text
    assert text.index("set -euo pipefail") < text.index("umask 077") < text.index("lib.sh")


@pytest.mark.parametrize("name", ALL_SHELL)
def test_scripts_are_valid_bash(name):
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_DIR / name)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr


def test_scripts_are_shellcheck_clean():
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed")

    result = subprocess.run(
        [shellcheck, "-x", "-s", "bash", *(str(DEPLOY_DIR / name) for name in ALL_SHELL)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout


FORBIDDEN = {
    r"--passphrase(?![-\w])": "gpg --passphrase puts the secret on the command line",
    r"--passphrase=": "gpg --passphrase=... puts the secret on the command line",
    r"--password": "a password option puts the secret on the command line",
    r"\s-W\b": "psql/pg_dump -W prompts for a password",
    r"PGPASSWORD=\S+[ \t]+\w": "PGPASSWORD=... command belongs in the environment, not in a command",
    r"echo\s+.*(PASSWORD|PASSPHRASE)": "never echo a secret",
    r"set\s+-x": "xtrace would print the secrets",
    r"\bcurl\b|\bwget\b": "backups must not be sent anywhere by these scripts",
}


@pytest.mark.parametrize("name", ALL_SHELL)
def test_scripts_contain_no_pattern_that_leaks_a_secret(name):
    code = "\n".join(
        line
        for line in (DEPLOY_DIR / name).read_text().splitlines()
        if not line.lstrip().startswith("#")
    )

    for pattern, reason in FORBIDDEN.items():
        assert not re.search(pattern, code), f"{name}: {reason}"


def test_the_passphrase_reaches_gpg_only_through_a_file():
    code = (DEPLOY_DIR / "lib.sh").read_text()

    assert '--passphrase-file "$BACKUP_PASSPHRASE_FILE"' in code
    assert "--pinentry-mode loopback" in code


def test_the_only_dump_command_is_a_pipe_into_gpg():
    code = (DEPLOY_DIR / "backup_db.sh").read_text()

    dump = re.search(
        r"^\s*pg_dump .*\|\s*\n\s*run_gpg .*--output \"\$partial_dump\"", code, re.MULTILINE
    )
    assert dump, "pg_dump must be piped straight into gpg"
    assert "--format=custom" in dump.group(0)
    assert "--symmetric --cipher-algo AES256" in dump.group(0)
    assert not re.search(r"pg_dump [^|\n]*(>|--file|-f\b)", code), "pg_dump must not write a file"


CRON_FIELDS = re.compile(r"^(\S+\s+){5}\S")


def test_crontab_example_schedules_every_required_job():
    lines = (DEPLOY_DIR / "crontab.example").read_text().splitlines()
    jobs = [line for line in lines if line.strip() and not line.lstrip().startswith("#")]
    schedules = [line for line in jobs if CRON_FIELDS.match(line) and not re.match(r"^\w+=", line)]
    text = "\n".join(schedules)

    assert "deploy/backup_db.sh" in text
    assert "deploy/restore_test.sh" in text
    assert "purge_pending_accounts" in text
    assert "clearsessions" in text
    for line in schedules:
        minute, hour, day, month, weekday = line.split()[:5]
        assert minute.isdigit() and hour.isdigit(), line
        assert (day, month, weekday).count("*") >= 2 or day.isdigit(), line
    assert not re.search(r"(PASSWORD|PASSPHRASE|SECRET)\w*=\S", "\n".join(jobs)), "no secrets"
    monthly = [line for line in schedules if "restore_test.sh" in line]
    assert len(monthly) == 1
    assert monthly[0].split()[2].isdigit(), "the restore test runs once a month, on a fixed day"


def test_guide_documents_every_variable_of_the_scripts():
    guide = GUIDE.read_text()

    for variable in SCRIPT_VARIABLES:
        assert variable in guide, f"{variable} is not described in {GUIDE.name}"


def test_guide_documents_every_variable_of_env_example():
    guide = GUIDE.read_text()
    names = re.findall(
        r"^([A-Z][A-Z0-9_]+)=", (REPO_DIR / ".env.example").read_text(), re.MULTILINE
    )

    assert names
    for name in names:
        assert name in guide, f"{name} from .env.example is not described in {GUIDE.name}"


def test_scripts_only_read_the_documented_variables():
    used = set()
    for name in ALL_SHELL:
        used |= set(
            re.findall(
                r"\b(BACKUP_[A-Z_]+|RESTORE_[A-Z_]+|POSTGRES_[A-Z_]+|BARF_[A-Z_]+)\b",
                (DEPLOY_DIR / name).read_text(),
            )
        )
    # Shell variables of the library and placeholders in usage texts, not environment variables.
    used -= {"BACKUP_NAME_RE", "BACKUP_STEM_RE", "BACKUP_FILE", "BACKUP_PATH"}

    assert used <= set(SCRIPT_VARIABLES), used - set(SCRIPT_VARIABLES)


def test_readme_links_the_guide_and_the_status_line_mentions_operations():
    readme = (REPO_DIR / "README.md").read_text()
    plan = (REPO_DIR / "docs" / "10-plan-mvp.md").read_text()

    assert "docs/13-nasazeni-a-provoz.md" in readme
    assert "deploy/" in readme
    assert "13-nasazeni-a-provoz.md" in plan
