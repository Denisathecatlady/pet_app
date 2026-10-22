# shellcheck shell=bash
# Helpers shared by backup_db.sh, restore_db.sh and restore_test.sh. This file is sourced,
# never executed. The sourcing script has already run "set -euo pipefail" and "umask 077"
# and has set SCRIPT_NAME.
#
# Conventions of all scripts
#   * configuration comes only from environment variables, optionally loaded from the file
#     named by BARF_ENV_FILE (load_env_file); nothing is read from the command line except
#     flags, and no secret ever appears in an argument list;
#   * the database password reaches libpq through PGPASSFILE or PGPASSWORD (setup_pg_env);
#   * exit status 0 = success, 1 = the operation failed, 2 = bad configuration, usage or a
#     safety rule refused the operation (nothing was changed).

# ASCII-only character ranges in the regular expressions below, stable sort order.
export LC_ALL=C

# One backup is barf-YYYYmmddTHHMMSSZ.dump.gpg (UTC) plus the manifest <name>.sha256 beside it.
# Pruning and restoring touch only files whose names match these patterns exactly.
BACKUP_STEM_RE='barf-20[0-9]{2}(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3])[0-5][0-9][0-5][0-9]Z\.dump\.gpg'
BACKUP_NAME_RE="^${BACKUP_STEM_RE}\$"
# shellcheck disable=SC2034  # used by backup_db.sh
MANIFEST_NAME_RE="^${BACKUP_STEM_RE}\\.sha256\$"
# PostgreSQL identifier subset accepted for database names: no "=" and no URI prefix,
# so libpq never reads the name as a connection string.
DB_NAME_RE='^[A-Za-z_][A-Za-z0-9_-]{0,62}$'
MIN_PASSPHRASE_LENGTH=20

utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
utc_stamp() { date -u +%Y%m%dT%H%M%SZ; }
# utc_stamp_at EPOCH: the time EPOCH (seconds since 1970) in the format of the backup names.
utc_stamp_at() { date -u -d "@$1" +%Y%m%dT%H%M%SZ; }

log() { printf '%s %s: %s\n' "$(utc_now)" "$SCRIPT_NAME" "$*" >&2; }

# die CODE MESSAGE...: log the message and exit with CODE.
die() {
  local code=$1
  shift
  log "ERROR: $*"
  exit "$code"
}

# is_readable_file FILE: succeeds for a regular, readable file.
is_readable_file() {
  [ -f "$1" ] && [ -r "$1" ]
}

# file_mode FILE: octal permission bits of FILE, following symbolic links.
file_mode() {
  stat -L -c '%a' -- "$1" 2>/dev/null || stat -L -f '%Lp' -- "$1"
}

# reject_loose_permissions FILE LABEL: refuse a file that group or others can access.
reject_loose_permissions() {
  local mode
  mode=$(file_mode "$1") || die 2 "$2: cannot read the permissions of $1"
  if (((8#$mode & 8#077) != 0)); then
    die 2 "$2 ($1) is accessible to group or others (mode $mode): run chmod 600"
  fi
}

# need_commands NAME...: refuse to start when a required program is not installed.
need_commands() {
  local name missing=()
  for name in "$@"; do
    command -v "$name" >/dev/null 2>&1 || missing+=("$name")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    die 2 "required program(s) not installed: ${missing[*]}"
  fi
}

# require_vars NAME...: every named variable must be set and non-empty.
require_vars() {
  local name missing=()
  for name in "$@"; do
    [ -n "${!name:-}" ] || missing+=("$name")
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    die 2 "required variable(s) not set: ${missing[*]}"
  fi
}

# validate_db_name VARIABLE: the value of VARIABLE must be a plain database name.
validate_db_name() {
  [[ ${!1} =~ $DB_NAME_RE ]] || die 2 "$1 must match $DB_NAME_RE"
}

# Names taken from the file of the backup scripts (BARF_ENV_FILE) and from the application file
# of the daily Django jobs (APP_ENV_FILE, run_manage.sh); any other name is skipped.
BARF_ENV_NAMES='^((POSTGRES|BACKUP|RESTORE)_[A-Z0-9_]*|PGPASSFILE|PGSSLMODE|PGSSLROOTCERT|GNUPGHOME)$'
# shellcheck disable=SC2034  # used by run_manage.sh
APP_ENV_NAMES='^(DJANGO|POSTGRES)_[A-Z0-9_]*$'

# load_env_file [FILE LABEL NAME_REGEX]: read NAME=value lines from FILE (default: the file named
# by BARF_ENV_FILE, label BARF_ENV_FILE, names BARF_ENV_NAMES). No file named = nothing to do.
#
# The file is parsed, never executed: a value such as $(command) or a secret key with $ & ( ) !
# is taken literally. It must be mode 600 or stricter. Blank lines and lines starting with #
# are ignored; a value may be wrapped in one pair of quotes; there is no variable expansion
# and no inline comment. Only names that match NAME_REGEX are taken (for BARF_ENV_FILE
# POSTGRES_*, BACKUP_*, RESTORE_*, PGPASSFILE, PGSSLMODE, PGSSLROOTCERT and GNUPGHOME), other
# names (for example the DJANGO_* lines of a file shared with the application) are skipped. A
# variable that is already set and non-empty in the environment wins over the file.
load_env_file() {
  local file=${1-${BARF_ENV_FILE:-}} label=${2:-BARF_ENV_FILE} allowed=${3:-$BARF_ENV_NAMES}
  local line name value number=0
  [ -n "$file" ] || return 0
  is_readable_file "$file" || die 2 "$label ($file) is not a readable file"
  reject_loose_permissions "$file" "$label"
  while IFS= read -r line || [ -n "$line" ]; do
    number=$((number + 1))
    if [[ $line =~ ^[[:space:]]*(#.*)?$ ]]; then
      continue
    fi
    if ! [[ $line =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]]; then
      die 2 "$label line $number: expected NAME=value"
    fi
    name=${BASH_REMATCH[1]}
    value=${BASH_REMATCH[2]}
    [[ $name =~ $allowed ]] || continue
    if [ -n "${!name:-}" ]; then
      continue
    fi
    if [[ ${#value} -ge 2 && ( $value == \"*\" || $value == \'*\' ) ]]; then
      value=${value:1:${#value}-2}
    fi
    export "$name=$value"
  done <"$file"
}

# require_tls_for_remote_host HOST: HOST is a unix-socket directory or the loopback interface, or
# PGSSLMODE is require, verify-ca or verify-full. libpq's default (prefer) falls back to plain
# text, which anybody on the path can force, so a remote server without a TLS setting is refused
# (exit 2). Use verify-full with PGSSLROOTCERT to also check the server's identity.
require_tls_for_remote_host() {
  case $1 in
    /* | localhost | 127.0.0.1 | ::1) return 0 ;;
  esac
  case ${PGSSLMODE:-} in
    require | verify-ca | verify-full) ;;
    *) die 2 "POSTGRES_HOST ($1) is not local: set PGSSLMODE to require, verify-ca or verify-full (now: ${PGSSLMODE:-not set}), or reach the server through localhost" ;;
  esac
}

# setup_pg_env: map the POSTGRES_* variables (the ones Django reads) to libpq's own and make
# sure a password source exists. Needs POSTGRES_USER, POSTGRES_HOST and optionally POSTGRES_PORT.
#
# Password, first match wins: PGPASSFILE (a file of mode 600; an inherited PGPASSWORD is removed
# so libpq really uses the file), else POSTGRES_PASSWORD (the variable the Django settings read;
# copied to PGPASSWORD for the child programs only), else an inherited PGPASSWORD. None of
# them is ever passed as an argument.
#
# A dump moves the whole database and the password exchange needs a protected channel, so a
# server that is not local must be reached over TLS: see require_tls_for_remote_host.
setup_pg_env() {
  [[ ${POSTGRES_PORT:-5432} =~ ^[0-9]{1,5}$ ]] || die 2 "POSTGRES_PORT must be a port number"
  unset PGHOSTADDR PGSERVICE PGSERVICEFILE PGDATABASE
  require_tls_for_remote_host "$POSTGRES_HOST"
  export PGHOST=$POSTGRES_HOST PGPORT=${POSTGRES_PORT:-5432} PGUSER=$POSTGRES_USER
  if [ -n "${PGPASSFILE:-}" ]; then
    is_readable_file "$PGPASSFILE" || die 2 "PGPASSFILE ($PGPASSFILE) is not a readable file"
    reject_loose_permissions "$PGPASSFILE" PGPASSFILE
    unset PGPASSWORD
  elif [ -n "${POSTGRES_PASSWORD:-}" ]; then
    export PGPASSWORD=$POSTGRES_PASSWORD
  elif [ -z "${PGPASSWORD:-}" ]; then
    die 2 "no database password: set POSTGRES_PASSWORD, PGPASSFILE or PGPASSWORD"
  fi
}

# pg_sql DATABASE [psql option...]: run SQL read from standard input in DATABASE and print
# bare result values. Use :'name' and :"name" with -v name=value for safe quoting.
# Never prompts for a password.
pg_sql() {
  local database=$1
  shift
  psql --no-psqlrc --no-password --quiet --tuples-only --no-align \
    --set ON_ERROR_STOP=1 --dbname="$database" "$@"
}

# maintenance_db: database used only for CREATE/DROP DATABASE and catalog queries
# (POSTGRES_MAINTENANCE_DB, default postgres).
maintenance_db() {
  local name=${POSTGRES_MAINTENANCE_DB:-postgres}
  [[ $name =~ $DB_NAME_RE ]] || die 2 "POSTGRES_MAINTENANCE_DB must match $DB_NAME_RE"
  printf '%s\n' "$name"
}

# reject_system_database VARIABLE: the value of VARIABLE must not be a database of the server
# itself (postgres, template0, template1) or the maintenance database. A restore into template1
# would copy the personal data into every database created later, and "pristine" template1 and
# postgres pass the check for an empty target.
reject_system_database() {
  local name=${!1}
  case $name in
    postgres | template0 | template1) die 2 "$1 ($name) is a system database of the server" ;;
  esac
  if [ "$name" = "$(maintenance_db)" ]; then
    die 2 "$1 ($name) is the maintenance database (POSTGRES_MAINTENANCE_DB)"
  fi
}

# db_exists NAME: succeeds when the database exists (asks the maintenance database).
db_exists() {
  local found
  found=$(pg_sql "$(maintenance_db)" -v "dbname=$1" <<'SQL'
SELECT count(*) FROM pg_catalog.pg_database WHERE datname = :'dbname';
SQL
  ) || die 1 "cannot query the PostgreSQL server (connection, password or privileges)"
  [ "$found" = 1 ]
}

# run_gpg ARGUMENT...: gpg in batch mode with the passphrase from BACKUP_PASSPHRASE_FILE.
#
# gpg starts a gpg-agent that outlives the script and keeps the environment it was started
# with, so the database passwords are removed from gpg's environment: it never needs them.
# --no-symkey-cache keeps the agent from caching the symmetric passphrase (GnuPG 2.2.7+).
run_gpg() {
  env -u PGPASSWORD -u POSTGRES_PASSWORD -u PGPASSFILE \
    gpg --batch --no-tty --quiet --pinentry-mode loopback --no-symkey-cache \
    --passphrase-file "$BACKUP_PASSPHRASE_FILE" "$@"
}

# check_backup_dir: BACKUP_DIR must be an absolute path to a directory that only the owner
# (and optionally the group) can reach. A world-accessible directory is refused.
check_backup_dir() {
  local mode
  [[ $BACKUP_DIR == /* ]] || die 2 "BACKUP_DIR must be an absolute path"
  [ -d "$BACKUP_DIR" ] || die 2 "BACKUP_DIR ($BACKUP_DIR) is not a directory: create it with install -d -m 700"
  if [ ! -w "$BACKUP_DIR" ] || [ ! -x "$BACKUP_DIR" ]; then
    die 2 "BACKUP_DIR ($BACKUP_DIR) is not writable"
  fi
  mode=$(file_mode "$BACKUP_DIR") || die 2 "cannot read the permissions of BACKUP_DIR"
  if (((8#$mode & 8#007) != 0)); then
    die 2 "BACKUP_DIR ($BACKUP_DIR) is accessible to other users (mode $mode): run chmod 700"
  fi
}

# check_passphrase_file: BACKUP_PASSPHRASE_FILE must be readable, private and not trivial.
# gpg reads the first line of the file as the passphrase.
check_passphrase_file() {
  local file=$BACKUP_PASSPHRASE_FILE line=''
  is_readable_file "$file" || die 2 "BACKUP_PASSPHRASE_FILE ($file) is not a readable file"
  reject_loose_permissions "$file" BACKUP_PASSPHRASE_FILE
  IFS= read -r line <"$file" || true
  if [ "${#line}" -lt "$MIN_PASSPHRASE_LENGTH" ]; then
    die 2 "the first line of BACKUP_PASSPHRASE_FILE must have at least $MIN_PASSPHRASE_LENGTH characters"
  fi
}

# list_backups DIRECTORY: names of the backup files in DIRECTORY, oldest first. Only regular
# files (not links, not directories) whose names match BACKUP_NAME_RE are listed.
list_backups() {
  local path name
  for path in "$1"/barf-*.dump.gpg; do
    name=${path##*/}
    [[ $name =~ $BACKUP_NAME_RE ]] || continue
    if [ -f "$path" ] && [ ! -L "$path" ]; then
      printf '%s\n' "$name"
    fi
  done | sort
}

# manifest_value FILE KEY: value of a "# KEY=value" line of a backup manifest (empty if absent).
manifest_value() {
  awk -v key="$2" 'index($0, "# " key "=") == 1 { print substr($0, length(key) + 4); exit }' "$1"
}

# resolve_backup_file PATH: absolute path of a backup file; refuses names that do not match
# BACKUP_NAME_RE, missing files and links.
resolve_backup_file() {
  local path=$1 directory name
  name=${path##*/}
  [[ $name =~ $BACKUP_NAME_RE ]] || die 2 "$name is not named like a backup (barf-YYYYmmddTHHMMSSZ.dump.gpg)"
  if [ ! -f "$path" ] || [ -L "$path" ]; then
    die 2 "$path is not a regular file"
  fi
  directory=$(cd -- "$(dirname -- "$path")" && pwd -P) || die 2 "cannot enter the directory of $path"
  printf '%s/%s\n' "$directory" "$name"
}

# verify_checksum BACKUP_FILE: compare the SHA-256 of BACKUP_FILE with its manifest
# (BACKUP_FILE.sha256). Returns 0 on a match; otherwise logs the reason and returns 1.
# The checksum detects damage and accidental changes; protection against a deliberate
# change comes from the authenticated encryption together with the secret passphrase.
verify_checksum() {
  local file=$1 manifest expected actual
  manifest="$file.sha256"
  if [ ! -f "$manifest" ] || [ -L "$manifest" ]; then
    log "manifest ${manifest##*/} is missing"
    return 1
  fi
  expected=$(awk -v name="${file##*/}" '$2 == name && $1 ~ /^[0-9a-f]{64}$/ { print $1; exit }' "$manifest")
  if [ -z "$expected" ]; then
    log "manifest ${manifest##*/} has no checksum line for ${file##*/}"
    return 1
  fi
  actual=$(sha256sum <"$file") || return 1
  actual=${actual%% *}
  if [ "$actual" != "$expected" ]; then
    log "checksum mismatch for ${file##*/}: the file is damaged or was changed"
    return 1
  fi
}
