#!/usr/bin/env bash
# backup_db.sh - encrypted logical backup of the BARF Nutri PostgreSQL database (docs/07 §7.7,
# docs/13-nasazeni-a-provoz.md).
#
# Usage:  backup_db.sh [--prune-only]
#
# pg_dump (custom format) is streamed through a pipe into "gpg --symmetric" (AES256), so an
# unencrypted dump never exists on disk. Result in BACKUP_DIR:
#     barf-YYYYmmddTHHMMSSZ.dump.gpg        the encrypted dump (UTC time of the backup)
#     barf-YYYYmmddTHHMMSSZ.dump.gpg.sha256 manifest: SHA-256 plus, as "# key=value" comment
#                                           lines, the table list and the row counts of the
#                                           user, animal and source tables at the time of the
#                                           dump (same database snapshot as the dump itself)
# The path of the new file is printed on standard output, messages go to standard error.
# After a successful backup the directory is pruned: the newest 30 backups and the first
# backup of each of the last 12 calendar months (months counted back from the newest
# backup) are kept, every other file that matches the backup name exactly is deleted.
# --prune-only prunes without making a backup (needs only BACKUP_DIR).
#
# Environment (or a file named by BARF_ENV_FILE, mode 600):
#   POSTGRES_DB, POSTGRES_USER, POSTGRES_HOST   what to dump, as for the Django settings
#   POSTGRES_PORT                               optional, default 5432
#   POSTGRES_PASSWORD | PGPASSFILE | PGPASSWORD one of them: the database password
#   BACKUP_DIR                                  absolute path, not accessible to other users
#   BACKUP_PASSPHRASE_FILE                      file (mode 600) whose first line is the
#                                               passphrase, at least 20 characters
# Exit status: 0 success, 1 the backup failed (nothing is left behind), 2 bad configuration.

set -euo pipefail
umask 077

SCRIPT_NAME=backup_db.sh
SCRIPT_DIR=$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")" && pwd -P)
# shellcheck source=lib.sh
# shellcheck source-path=SCRIPTDIR
. "$SCRIPT_DIR/lib.sh"

# Retention (docs/07 §7.7): fixed on purpose, a wrong value would silently delete backups.
KEEP_NEWEST=30
KEEP_MONTHS=12
# Tables whose row counts are recorded in the manifest (when the table exists).
COUNTED_TABLES=(accounts_user animals_animal catalog_scientificsource)
SNAPSHOT_END='__barf_end_of_result__'

partial_dump=''
partial_manifest=''

stop_snapshot_session() {
  [ -n "${SNAP_PID:-}" ] || return 0
  kill "$SNAP_PID" 2>/dev/null || true
  wait "$SNAP_PID" 2>/dev/null || true
}

cleanup() {
  stop_snapshot_session
  [ -z "$partial_dump" ] || rm -f -- "$partial_dump"
  [ -z "$partial_manifest" ] || rm -f -- "$partial_manifest"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM PIPE

# start_snapshot_session: one psql session in a REPEATABLE READ transaction that exports its
# snapshot. pg_dump --snapshot reads exactly this state, and so do the table list and the row
# counts, so the manifest matches the dump even while the application keeps writing.
start_snapshot_session() {
  coproc SNAP {
    exec psql --no-psqlrc --no-password --quiet --tuples-only --no-align \
      --set ON_ERROR_STOP=1 --dbname="$POSTGRES_DB"
  }
  snap_query "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;" >/dev/null ||
    die 1 "cannot open a session on database $POSTGRES_DB"
}

# snap_query SQL: run one statement in the snapshot session and print its result rows.
snap_query() {
  local line
  printf '%s\n\\echo %s\n' "$1" "$SNAPSHOT_END" >&"${SNAP[1]}" || return 1
  while IFS= read -r -t 120 -u "${SNAP[0]}" line; do
    if [ "$line" = "$SNAPSHOT_END" ]; then
      return 0
    fi
    printf '%s\n' "$line"
  done
  return 1
}

# write_manifest FILE_NAME SHA256 SNAPSHOT_FACTS: write the manifest to $partial_manifest.
write_manifest() {
  {
    printf '# barf backup manifest v1\n'
    printf '%s\n' "$3"
    printf '%s  %s\n' "$2" "$1"
  } >"$partial_manifest"
}

# month_index NAME: running number of the calendar month of a backup name (year * 12 + month).
month_index() {
  echo $((10#${1:5:4} * 12 + 10#${1:9:2}))
}

# prune_backups DIRECTORY: apply the retention rule to DIRECTORY (see the header).
# Only regular files whose name matches the backup pattern exactly are ever deleted, together
# with their manifest. Manifests of backups that no longer exist are deleted too.
prune_backups() {
  local directory=$1 name path index newest_index total i
  local names=() deleted=0
  local -A keep=() seen=()
  while IFS= read -r name; do
    names+=("$name")
  done < <(list_backups "$directory")
  total=${#names[@]}
  if [ "$total" -gt 0 ]; then
    for ((i = total > KEEP_NEWEST ? total - KEEP_NEWEST : 0; i < total; i++)); do
      keep[${names[i]}]=1
    done
    newest_index=$(month_index "${names[total - 1]}")
    for name in "${names[@]}"; do
      index=$(month_index "$name")
      if [ -z "${seen[$index]:-}" ]; then
        seen[$index]=1
        if [ "$index" -gt $((newest_index - KEEP_MONTHS)) ]; then
          keep[$name]=1
        fi
      fi
    done
    for name in "${names[@]}"; do
      if [ -z "${keep[$name]:-}" ]; then
        rm -f -- "$directory/$name" "$directory/$name.sha256"
        deleted=$((deleted + 1))
        log "pruned $name"
      fi
    done
  fi
  for path in "$directory"/barf-*.dump.gpg.sha256; do
    name=${path##*/}
    [[ $name =~ $MANIFEST_NAME_RE ]] || continue
    if [ -f "$path" ] && [ ! -L "$path" ] && [ ! -e "${path%.sha256}" ] && [ ! -L "${path%.sha256}" ]; then
      rm -f -- "$path"
      log "pruned orphan manifest $name"
    fi
  done
  log "retention: $((total - deleted)) backup(s) kept, $deleted deleted"
}

make_backup() {
  local stamp name final manifest snapshot tables tables_csv count table facts version digest size
  stamp=$(utc_stamp)
  name="barf-$stamp.dump.gpg"
  final="$BACKUP_DIR/$name"
  manifest="$final.sha256"
  if [ -e "$final" ] || [ -L "$final" ] || [ -e "$manifest" ] || [ -L "$manifest" ]; then
    die 1 "$name already exists (two backups within one second?)"
  fi

  start_snapshot_session
  snapshot=$(snap_query "SELECT pg_export_snapshot();") || die 1 "cannot export a database snapshot"
  version=$(snap_query "SHOW server_version;") || die 1 "cannot read the server version"
  tables=$(snap_query "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY tablename;") ||
    die 1 "cannot list the tables"
  tables_csv=$(printf '%s\n' "$tables" | paste -sd, -)
  facts="# created=$stamp"$'\n'"# database=$POSTGRES_DB"$'\n'"# server_version=$version"
  facts+=$'\n'"# tables=$tables_csv"
  for table in "${COUNTED_TABLES[@]}"; do
    if [[ ",$tables_csv," == *",$table,"* ]]; then
      count=$(snap_query "SELECT count(*) FROM public.$table;") || die 1 "cannot count rows of $table"
      [[ $count =~ ^[0-9]+$ ]] || die 1 "unexpected row count of $table: $count"
      facts+=$'\n'"# count.$table=$count"
    fi
  done

  partial_dump=$(mktemp "$BACKUP_DIR/.barf-partial.XXXXXX")
  partial_manifest=$(mktemp "$BACKUP_DIR/.barf-partial.XXXXXX")

  log "dumping database $POSTGRES_DB (snapshot $snapshot)"
  pg_dump --no-password --format=custom --snapshot="$snapshot" --dbname="$POSTGRES_DB" |
    run_gpg --yes --symmetric --cipher-algo AES256 --compress-algo none --output "$partial_dump" ||
    die 1 "pg_dump or gpg failed, no backup was written"
  stop_snapshot_session

  # The archive must decrypt and be readable by pg_restore (the drain keeps gpg from getting
  # a broken pipe when pg_restore stops reading after the table of contents).
  run_gpg --decrypt -- "$partial_dump" | { pg_restore --list >/dev/null && cat >/dev/null; } ||
    die 1 "the new backup does not decrypt to a readable PostgreSQL archive"

  digest=$(sha256sum <"$partial_dump") || die 1 "cannot compute the checksum"
  digest=${digest%% *}
  write_manifest "$name" "$digest" "$facts"
  sync -- "$partial_dump" "$partial_manifest" 2>/dev/null || true
  mv -n -- "$partial_dump" "$final"
  partial_dump=''
  mv -n -- "$partial_manifest" "$manifest"
  partial_manifest=''
  if [ ! -f "$final" ] || [ ! -f "$manifest" ]; then
    die 1 "could not move the backup into place"
  fi
  size=$(wc -c <"$final")
  log "backup written: $name ($((size)) bytes), manifest $name.sha256"
  printf '%s\n' "$final"
}

main() {
  local prune_only=0
  case "${1:-}" in
    '') ;;
    --prune-only) prune_only=1 ;;
    *) die 2 "usage: backup_db.sh [--prune-only]" ;;
  esac
  [ "$#" -le 1 ] || die 2 "usage: backup_db.sh [--prune-only]"

  load_env_file
  if [ "$prune_only" = 1 ]; then
    require_vars BACKUP_DIR
    check_backup_dir
    prune_backups "$BACKUP_DIR"
    return 0
  fi

  require_vars POSTGRES_DB POSTGRES_USER POSTGRES_HOST BACKUP_DIR BACKUP_PASSPHRASE_FILE
  validate_db_name POSTGRES_DB
  check_backup_dir
  check_passphrase_file
  need_commands pg_dump pg_restore psql gpg sha256sum
  setup_pg_env
  make_backup
  prune_backups "$BACKUP_DIR"
}

main "$@"
