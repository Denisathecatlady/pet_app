"""deploy/run_manage.sh: the daily Django jobs read the application's env file without running it.

The crontab used to load /etc/barf/app.env with ``bash -c 'set -a; . file'``. The documented
secret-key generator (``get_random_secret_key``) produces characters such as ``$ & ( ) ! #``
that a shell reads as syntax, so an unquoted key was usually broken or silently altered, and
any quoting mistake in a secrets file ran as code. The script parses the file instead.

The tests use a copy of the scripts in a fake checkout whose ``.venv/bin/python`` only records
the working directory, the arguments and the environment it was started with.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from django.core.management.utils import get_random_secret_key

from tests.ops.helpers import DEPLOY_DIR

FAKE_PYTHON = """#!/bin/sh
{
  printf 'cwd=%s\\n' "$PWD"
  for argument in "$@"; do printf 'arg=%s\\n' "$argument"; done
  env | sed 's/^/env:/'
} > "$RECORD"
"""


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """A fake checkout: deploy/ (copies of the scripts), backend/manage.py, .venv/bin/python."""
    root = tmp_path / "barf"
    (root / "deploy").mkdir(parents=True)
    for name in ("run_manage.sh", "lib.sh"):
        shutil.copy2(DEPLOY_DIR / name, root / "deploy" / name)
    (root / "backend").mkdir()
    (root / "backend" / "manage.py").write_text("# fake\n")
    python = root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text(FAKE_PYTHON)
    python.chmod(0o755)
    return root


def write_env(path: Path, text: str, mode: int = 0o600) -> Path:
    path.write_text(text)
    path.chmod(mode)
    return path


def run(
    checkout: Path, *args: str, env_file: Path | None = None, **env: str
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run run_manage.sh; return the process and the environment the fake python recorded."""
    record = checkout / "record.txt"
    record.unlink(missing_ok=True)
    variables = {"PATH": os.environ["PATH"], "RECORD": str(record), "LANG": "C", **env}
    if env_file is not None:
        variables["APP_ENV_FILE"] = str(env_file)
    result = subprocess.run(
        [str(checkout / "deploy" / "run_manage.sh"), *args],
        env=variables,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    recorded: dict[str, str] = {}
    if record.exists():
        for line in record.read_text().splitlines():
            if line.startswith("env:"):
                name, _, value = line[4:].partition("=")
                recorded[name] = value
            elif line.startswith("cwd="):
                recorded["cwd"] = line[4:]
        recorded["args"] = "\n".join(
            line[4:] for line in record.read_text().splitlines() if line.startswith("arg=")
        )
    return result, recorded


def test_runs_manage_py_in_backend_with_the_arguments_and_the_variables(checkout):
    env_file = write_env(
        checkout / "app.env",
        "# application\n\nDJANGO_SECRET_KEY=abc\nPOSTGRES_DB=barf\n"
        "DJANGO_ALLOWED_HOSTS=barf.example.cz\n",
    )

    result, seen = run(checkout, "clearsessions", "--verbosity", "0", env_file=env_file)

    assert result.returncode == 0, result.stderr
    assert seen["cwd"] == str(checkout / "backend")
    assert seen["args"].splitlines() == ["manage.py", "clearsessions", "--verbosity", "0"]
    assert seen["DJANGO_SECRET_KEY"] == "abc"
    assert seen["POSTGRES_DB"] == "barf"
    assert seen["DJANGO_SETTINGS_MODULE"] == "config.settings.prod"


def test_the_settings_module_can_be_chosen(checkout):
    env_file = write_env(checkout / "app.env", "DJANGO_SETTINGS_MODULE=config.settings.dev\n")

    _, seen = run(checkout, "check", env_file=env_file)

    assert seen["DJANGO_SETTINGS_MODULE"] == "config.settings.dev"


def test_generated_secret_keys_arrive_unchanged(checkout):
    """Of 200 generated keys only a few survive ``. file`` in a shell; all survive here."""
    for _ in range(200):
        key = get_random_secret_key()
        env_file = write_env(checkout / "app.env", f"DJANGO_SECRET_KEY={key}\n")

        result, seen = run(checkout, "clearsessions", env_file=env_file)

        assert result.returncode == 0, (key, result.stderr)
        assert seen["DJANGO_SECRET_KEY"] == key


def test_the_file_is_never_executed(checkout):
    marker = checkout / "pwned"
    env_file = write_env(
        checkout / "app.env",
        f"DJANGO_A=$(touch {marker})\nDJANGO_B=x; touch {marker}\nDJANGO_C=`touch {marker}`\n"
        f"DJANGO_D=a&touch {marker}\nDJANGO_E=$HOME\n",
    )

    result, seen = run(checkout, "clearsessions", env_file=env_file)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert seen["DJANGO_A"] == f"$(touch {marker})"
    assert seen["DJANGO_B"] == f"x; touch {marker}"
    assert seen["DJANGO_E"] == "$HOME"


def test_one_pair_of_quotes_is_removed(checkout):
    env_file = write_env(
        checkout / "app.env",
        "DJANGO_DEFAULT_FROM_EMAIL='BARF Nutri <noreply@barf.example.cz>'\n"
        'DJANGO_CONTACT_EMAIL="podpora@barf.example.cz"\n'
        "DJANGO_LOG_LEVEL=\n",
    )

    _, seen = run(checkout, "check", env_file=env_file)

    assert seen["DJANGO_DEFAULT_FROM_EMAIL"] == "BARF Nutri <noreply@barf.example.cz>"
    assert seen["DJANGO_CONTACT_EMAIL"] == "podpora@barf.example.cz"


def test_only_django_and_postgres_names_are_taken(checkout):
    env_file = write_env(
        checkout / "app.env",
        "PATH=/nowhere\nLD_PRELOAD=/tmp/evil.so\nPYTHONPATH=/tmp/evil\nBASH_ENV=/tmp/evil\n"
        "DJANGO_SECRET_KEY=abc\nBACKUP_DIR=/tmp/not-for-django\n",
    )

    result, seen = run(checkout, "check", env_file=env_file)

    assert result.returncode == 0, result.stderr
    assert seen["PATH"] == os.environ["PATH"]
    for name in ("LD_PRELOAD", "PYTHONPATH", "BASH_ENV", "BACKUP_DIR"):
        assert name not in seen, name
    assert seen["DJANGO_SECRET_KEY"] == "abc"


def test_the_environment_wins_over_the_file(checkout):
    env_file = write_env(checkout / "app.env", "DJANGO_LOG_LEVEL=DEBUG\nDJANGO_X=from-file\n")

    _, seen = run(checkout, "check", env_file=env_file, DJANGO_LOG_LEVEL="WARNING")

    assert seen["DJANGO_LOG_LEVEL"] == "WARNING"
    assert seen["DJANGO_X"] == "from-file"


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o666])
def test_a_file_others_can_read_is_refused(checkout, mode):
    env_file = write_env(checkout / "app.env", "DJANGO_SECRET_KEY=abc\n", mode)

    result, seen = run(checkout, "clearsessions", env_file=env_file)

    assert result.returncode == 2
    assert "APP_ENV_FILE" in result.stderr and "chmod 600" in result.stderr
    assert seen == {}, "manage.py must not have been started"


def test_configuration_errors_start_nothing(checkout):
    good = write_env(checkout / "app.env", "DJANGO_SECRET_KEY=abc\n")
    bad = write_env(checkout / "bad.env", "DJANGO_SECRET_KEY=abc\nnot a variable line\n")
    cases = {
        "no command": run(checkout, env_file=good),
        "no APP_ENV_FILE": run(checkout, "check"),
        "missing file": run(checkout, "check", env_file=checkout / "missing.env"),
        "malformed line": run(checkout, "check", env_file=bad),
    }

    for name, (result, seen) in cases.items():
        assert result.returncode == 2, name
        assert seen == {}, name
    assert "line 2" in cases["malformed line"][0].stderr
    assert "APP_ENV_FILE" in cases["no APP_ENV_FILE"][0].stderr


def test_a_missing_virtualenv_is_a_configuration_error(checkout):
    env_file = write_env(checkout / "app.env", "DJANGO_SECRET_KEY=abc\n")
    (checkout / ".venv" / "bin" / "python").unlink()

    result, _ = run(checkout, "check", env_file=env_file)

    assert result.returncode == 2
    assert ".venv" in result.stderr


def test_the_exit_status_of_manage_py_is_passed_on(checkout):
    env_file = write_env(checkout / "app.env", "DJANGO_SECRET_KEY=abc\n")
    python = checkout / ".venv" / "bin" / "python"
    python.write_text("#!/bin/sh\nexit 7\n")
    python.chmod(stat.S_IRWXU)

    result, _ = run(checkout, "check", env_file=env_file)

    assert result.returncode == 7
