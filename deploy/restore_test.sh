#!/usr/bin/env bash
# restore_test.sh - the monthly restore test required by docs/07 §7.7
# (procedure and protocol: docs/13-nasazeni-a-provoz.md).
#
# Usage:  restore_test.sh
#
# Restores the newest backup in BACKUP_DIR into a scratch database named
# barf_restore_test_<UTC timestamp> (through restore_db.sh --create), then checks:
#   * the tables of the application schema (public) exist: the fixed minimum list below and,
#     when the manifest recorded one, exactly the table list of the live database at backup time;
#   * the rows of the user, animal and scientific source tables are counted and compared with
#     the counts the manifest recorded at the time of the backup (same snapshot as the dump).
#     A backup without recorded counts is not compared, the counts are only reported.
# The scratch database is always dropped again (a database that cannot be dropped is a FAIL,
# because it would keep a copy of personal data). One line is appended to RESTORE_TEST_LOG:
#   <UTC time> file=<backup> result=OK|FAIL users=<n> animals=<n> sources=<n> note=<text>
# and also printed on standard output. Counts that could not be read are "-".
#
# Environment (or a file named by BARF_ENV_FILE, mode 600): POSTGRES_DB, POSTGRES_USER,
# POSTGRES_HOST, POSTGRES_PORT, POSTGRES_PASSWORD | PGPASSFILE | PGPASSWORD, BACKUP_DIR,
# BACKUP_PASSPHRASE_FILE, RESTORE_TEST_LOG (absolute path of the protocol file, its directory
# must exist), POSTGRES_MAINTENANCE_DB (optional). The database role needs CREATEDB.
# Exit status: 0 OK, 1 FAIL, 2 bad configuration (no test was run, no line was written).

set -euo pipefail
umask 077

SCRIPT_NAME=restore_test.sh
SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd -P)
# shellcheck source=lib.sh
# shellcheck source-path=SCRIPTDIR
. "$SCRIPT_DIR/lib.sh"

SCRATCH_PREFIX=barf_restore_test_
# Tables that must exist in every restored backup of the application.
REQUIRED_TABLES=(django_migrations accounts_user animals_animal animals_bodymeasurement catalog_scientificsource)

scratch=''
scratch_ours=0
note=''
users='-'
animals='-'
sources='-'

# drop_scratch: drop the scratch database, but only one that this run created and only one
# whose name starts with the fixed prefix.
drop_scratch() {
  [ "$scratch_ours" = 1 ] || return 0
  [[ $scratch == "$SCRATCH_PREFIX"* ]] || return 1
  pg_sql "$(maintenance_db)" -v "dbname=$scratch" <<'SQL' || return 1
DROP DATABASE IF EXISTS :"dbname";
SQL
  scratch_ours=0
}

cleanup() {
  drop_scratch || log "WARNING: could not drop the scratch database $scratch, drop it by hand"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM PIPE

# count_rows TABLE: rows of public.TABLE in the scratch database.
count_rows() {
  pg_sql "$scratch" <<SQL
SELECT count(*) FROM public.$1;
SQL
}

# run_checks BACKUP_PATH: restore and check; sets note/users/animals/sources, returns 1 on failure.
run_checks() {
  local path=$1 manifest tables table absent='' expected recorded mismatches=''
  manifest="$path.sha256"

  if db_exists "$scratch"; then
    note="scratch database $scratch already exists"
    return 1
  fi
  scratch_ours=1
  if ! RESTORE_TARGET_DB=$scratch "$SCRIPT_DIR/restore_db.sh" --create "$path" >/dev/null; then
    note="restore into $scratch failed (see the messages above)"
    return 1
  fi

  tables=$(pg_sql "$scratch" <<'SQL'
SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename;
SQL
  ) || { note="cannot list the tables of $scratch"; return 1; }
  tables=$(printf '%s\n' "$tables" | paste -sd, -)

  for table in "${REQUIRED_TABLES[@]}"; do
    [[ ",$tables," == *",$table,"* ]] || absent+="$table "
  done
  if [ -n "$absent" ]; then
    note="missing tables: ${absent% }"
    return 1
  fi
  expected=$(manifest_value "$manifest" tables)
  if [ -n "$expected" ] && [ "$expected" != "$tables" ]; then
    note="the table list differs from the manifest"
    return 1
  fi

  users=$(count_rows accounts_user) || { note="cannot count accounts_user"; return 1; }
  animals=$(count_rows animals_animal) || { note="cannot count animals_animal"; return 1; }
  sources=$(count_rows catalog_scientificsource) || { note="cannot count catalog_scientificsource"; return 1; }

  recorded=0
  for table in accounts_user animals_animal catalog_scientificsource; do
    expected=$(manifest_value "$manifest" "count.$table")
    [ -n "$expected" ] || continue
    recorded=$((recorded + 1))
    case $table in
      accounts_user) [ "$users" = "$expected" ] || mismatches+="users $users != $expected " ;;
      animals_animal) [ "$animals" = "$expected" ] || mismatches+="animals $animals != $expected " ;;
      catalog_scientificsource) [ "$sources" = "$expected" ] || mismatches+="sources $sources != $expected " ;;
    esac
  done
  if [ -n "$mismatches" ]; then
    note="counts differ from the manifest: ${mismatches% }"
    return 1
  fi
  if [ "$recorded" -eq 3 ]; then
    note="tables present, counts equal the manifest"
  else
    note="tables present, counts only reported (not recorded in the manifest)"
  fi
}

main() {
  [ "$#" -eq 0 ] || die 2 "usage: restore_test.sh (configuration only through the environment)"
  load_env_file
  require_vars POSTGRES_DB POSTGRES_USER POSTGRES_HOST BACKUP_DIR BACKUP_PASSPHRASE_FILE RESTORE_TEST_LOG
  validate_db_name POSTGRES_DB
  check_backup_dir
  check_passphrase_file
  need_commands pg_restore psql gpg sha256sum
  setup_pg_env
  [[ $RESTORE_TEST_LOG == /* ]] || die 2 "RESTORE_TEST_LOG must be an absolute path"
  [ -d "$(dirname -- "$RESTORE_TEST_LOG")" ] || die 2 "the directory of RESTORE_TEST_LOG does not exist"
  [ ! -L "$RESTORE_TEST_LOG" ] || die 2 "RESTORE_TEST_LOG is a symbolic link"
  { : >>"$RESTORE_TEST_LOG"; } 2>/dev/null || die 2 "cannot append to RESTORE_TEST_LOG ($RESTORE_TEST_LOG)"

  scratch="$SCRATCH_PREFIX$(utc_stamp | tr '[:upper:]' '[:lower:]')"
  validate_db_name scratch

  local newest='' backup_path='' result=FAIL line
  newest=$(list_backups "$BACKUP_DIR" | tail -n 1)
  if [ -z "$newest" ]; then
    note="no backup found in BACKUP_DIR"
  else
    backup_path="$BACKUP_DIR/$newest"
    log "testing the newest backup $newest in $scratch"
    if run_checks "$backup_path"; then
      result=OK
    fi
  fi

  if ! drop_scratch; then
    result=FAIL
    note="$note; the scratch database $scratch could not be dropped"
  fi

  note=${note//[$'\t\r\n']/ }
  line="$(utc_now) file=${newest:--} result=$result users=$users animals=$animals sources=$sources note=${note:0:300}"
  printf '%s\n' "$line" >>"$RESTORE_TEST_LOG" || die 1 "cannot write the protocol line to RESTORE_TEST_LOG"
  printf '%s\n' "$line"
  [ "$result" = OK ] || exit 1
}

main "$@"
