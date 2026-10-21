#!/usr/bin/env bash
# restore_db.sh - restore an encrypted backup made by backup_db.sh (docs/13-nasazeni-a-provoz.md).
#
# Usage:  restore_db.sh [--create] [--i-know-this-overwrites-production] BACKUP_FILE
#
#   BACKUP_FILE   barf-YYYYmmddTHHMMSSZ.dump.gpg with its manifest BACKUP_FILE.sha256 beside it
#   --create      create the target database if it does not exist (UTF8, template0)
#   --i-know-this-overwrites-production
#                 required when RESTORE_TARGET_DB is the database named by POSTGRES_DB (the live
#                 one). The restore then replaces the tables of the backup (pg_restore --clean).
#                 Stop the application first. Objects that are not in the backup are left alone.
#
# Steps: check the manifest checksum; decrypt once to nowhere (wrong passphrase or damaged
# file are found before the database is touched); then decrypt into a pipe and run
# "pg_restore --no-owner --no-privileges --single-transaction", so a failed restore changes
# nothing. Without the production flag the target must be empty. If this run created the
# target and the restore fails, the new database is dropped again.
#
# Environment (or a file named by BARF_ENV_FILE, mode 600):
#   RESTORE_TARGET_DB                           database to restore into
#   POSTGRES_DB                                 the live database (guarded, see above)
#   POSTGRES_USER, POSTGRES_HOST, POSTGRES_PORT, POSTGRES_PASSWORD | PGPASSFILE | PGPASSWORD
#   BACKUP_PASSPHRASE_FILE                      file (mode 600), first line = passphrase
#   POSTGRES_MAINTENANCE_DB                     optional, default postgres (for CREATE DATABASE)
# Exit status: 0 success, 1 the restore failed, 2 bad configuration or a safety rule refused it.

set -euo pipefail
umask 077

SCRIPT_NAME=restore_db.sh
SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd -P)
# shellcheck source=lib.sh
# shellcheck source-path=SCRIPTDIR
. "$SCRIPT_DIR/lib.sh"

created_database=''

cleanup() {
  if [ -n "$created_database" ]; then
    log "dropping the database $created_database that this run created"
    pg_sql "$(maintenance_db)" -v "dbname=$created_database" <<'SQL' || log "WARNING: could not drop $created_database, drop it by hand"
DROP DATABASE IF EXISTS :"dbname";
SQL
  fi
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM PIPE

main() {
  local create=0 production_ok=0 file='' arg
  for arg in "$@"; do
    case $arg in
      --create) create=1 ;;
      --i-know-this-overwrites-production) production_ok=1 ;;
      -*) die 2 "unknown option $arg (usage: restore_db.sh [--create] [--i-know-this-overwrites-production] BACKUP_FILE)" ;;
      *)
        [ -z "$file" ] || die 2 "only one BACKUP_FILE can be given"
        file=$arg
        ;;
    esac
  done
  [ -n "$file" ] || die 2 "usage: restore_db.sh [--create] [--i-know-this-overwrites-production] BACKUP_FILE"

  load_env_file
  require_vars RESTORE_TARGET_DB POSTGRES_DB POSTGRES_USER POSTGRES_HOST BACKUP_PASSPHRASE_FILE
  validate_db_name RESTORE_TARGET_DB
  validate_db_name POSTGRES_DB

  local overwrite=0
  if [ "$RESTORE_TARGET_DB" = "$POSTGRES_DB" ]; then
    if [ "$production_ok" != 1 ]; then
      die 2 "RESTORE_TARGET_DB is the live database ($POSTGRES_DB): refusing. Restore into another database, or add --i-know-this-overwrites-production"
    fi
    overwrite=1
  fi

  check_passphrase_file
  need_commands pg_restore psql gpg sha256sum
  setup_pg_env
  file=$(resolve_backup_file "$file")

  verify_checksum "$file" || die 1 "the backup failed the checksum check, nothing was restored"
  run_gpg --decrypt -- "$file" >/dev/null ||
    die 1 "cannot decrypt ${file##*/} (wrong passphrase or damaged file), nothing was restored"

  if db_exists "$RESTORE_TARGET_DB"; then
    if [ "$overwrite" = 0 ]; then
      local tables
      tables=$(pg_sql "$RESTORE_TARGET_DB" <<'SQL'
SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema');
SQL
      ) || die 1 "cannot inspect the database $RESTORE_TARGET_DB"
      [ "$tables" = 0 ] || die 2 "the database $RESTORE_TARGET_DB is not empty ($tables tables): restore into an empty or new database (--create)"
    fi
  else
    [ "$create" = 1 ] || die 2 "the database $RESTORE_TARGET_DB does not exist: add --create to create it"
    pg_sql "$(maintenance_db)" -v "dbname=$RESTORE_TARGET_DB" <<'SQL' || die 1 "cannot create the database $RESTORE_TARGET_DB (the role needs CREATEDB)"
CREATE DATABASE :"dbname" TEMPLATE template0 ENCODING 'UTF8';
SQL
    created_database=$RESTORE_TARGET_DB
    log "created database $RESTORE_TARGET_DB"
  fi

  local restore_options=(--no-password --no-owner --no-privileges --single-transaction --exit-on-error)
  if [ "$overwrite" = 1 ]; then
    restore_options+=(--clean --if-exists)
    log "WARNING: replacing the content of the live database $POSTGRES_DB"
  fi
  log "restoring ${file##*/} into $RESTORE_TARGET_DB"
  run_gpg --decrypt -- "$file" | pg_restore "${restore_options[@]}" --dbname="$RESTORE_TARGET_DB" ||
    die 1 "pg_restore failed, the database $RESTORE_TARGET_DB was left unchanged"
  created_database=''
  # Statistics are not part of a dump; analyze the application tables (not the shared catalogs).
  pg_sql "$RESTORE_TARGET_DB" <<'SQL' || log "WARNING: ANALYZE failed (the data was restored; run ANALYZE by hand)"
SELECT format('ANALYZE %s', c.oid::regclass)
FROM pg_catalog.pg_class AS c
JOIN pg_catalog.pg_namespace AS n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm', 'p')
\gexec
SQL
  log "restore finished: ${file##*/} -> $RESTORE_TARGET_DB"
}

main "$@"
