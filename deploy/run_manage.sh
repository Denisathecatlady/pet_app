#!/usr/bin/env bash
# run_manage.sh - run one "manage.py" command of the application with the variables of the
# application's environment file (the daily jobs of docs/13-nasazeni-a-provoz.md §13.7).
#
# Usage:  run_manage.sh COMMAND [ARGUMENT...]      e.g.  run_manage.sh clearsessions
#
# The file named by APP_ENV_FILE (mode 600, the variables of .env.example) is PARSED, never
# executed by a shell: a secret key such as 'a$b&c(d)!e' or a value with $(...) is taken
# literally, and a quoting mistake cannot run a command. Rules as for BARF_ENV_FILE of the
# backup scripts:
# NAME=value lines, # comments on their own lines, one pair of quotes around a value is removed,
# no variable expansion. Only DJANGO_* and POSTGRES_* names are taken; a variable that is already
# set in the environment wins over the file. DJANGO_SETTINGS_MODULE defaults to
# config.settings.prod.
#
# The command runs as the user of the caller with the virtualenv of the checkout this script
# belongs to: <checkout>/.venv/bin/python manage.py in <checkout>/backend.
# Exit status: the status of manage.py; 2 = bad configuration or usage (nothing was run).

set -euo pipefail
umask 077

SCRIPT_NAME=run_manage.sh
SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd -P)
# shellcheck source=lib.sh
# shellcheck source-path=SCRIPTDIR
. "$SCRIPT_DIR/lib.sh"

main() {
  [ "$#" -ge 1 ] || die 2 "usage: run_manage.sh COMMAND [ARGUMENT...]"
  require_vars APP_ENV_FILE
  load_env_file "$APP_ENV_FILE" APP_ENV_FILE "$APP_ENV_NAMES"
  export DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE:-config.settings.prod}

  local root=${SCRIPT_DIR%/*} python
  python=$root/.venv/bin/python
  [ -x "$python" ] || die 2 "$python is not an executable: create the virtualenv of the checkout ($root/.venv)"
  [ -f "$root/backend/manage.py" ] || die 2 "$root/backend/manage.py not found"
  cd -- "$root/backend"
  exec "$python" manage.py "$@"
}

main "$@"
