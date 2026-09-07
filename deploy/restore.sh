#!/usr/bin/env bash
# Restores a gzip-compressed pg_dump produced by deploy/backup.sh into a
# running fcculs Postgres container.
#
# Guarded behind an explicit --confirm flag on purpose: this is a
# destructive operation (it drops and recreates every object in the target
# database before loading the dump) and must never run accidentally against
# a production database just because someone tab-completed the wrong
# script. Also supports restoring into a *different* database name
# (--db-name) so you can restore into a disposable/throwaway database
# alongside the live one for verification (e.g. comparing row counts)
# without ever touching production data -- this is the recommended way to
# actually test a backup.
#
# Usage:
#   deploy/restore.sh --confirm /path/to/fcculs-fcculs-20240101-120000.sql.gz
#   deploy/restore.sh --confirm --db-name fcculs_restore_test /path/to/dump.sql.gz
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"

usage() {
  cat <<'USAGE'
Usage: deploy/restore.sh --confirm [--db-name NAME] <dump-file.sql.gz>

  --confirm       Required. Without it, the script only prints what it
                  would do and exits -- this is a destructive operation.
  --db-name NAME  Restore into database NAME instead of the configured
                  POSTGRES_DB. Use this to restore into a disposable test
                  database alongside the live one (recommended way to
                  verify a backup is actually restorable).

Example (verify a backup without touching the live database):
  createdb-equivalent via podman exec; then:
  deploy/restore.sh --confirm --db-name fcculs_restore_test \
    ~/fcculs-backups/fcculs-fcculs-20240101-120000.sql.gz
USAGE
}

CONFIRM=0
DB_NAME_OVERRIDE=""
DUMP_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --confirm) CONFIRM=1; shift ;;
    --db-name) DB_NAME_OVERRIDE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*)
      echo "Unknown option: $1 (see --help)" >&2
      exit 1
      ;;
    *)
      DUMP_FILE="$1"; shift ;;
  esac
done

if [[ -z "$DUMP_FILE" ]]; then
  echo "ERROR: no dump file given." >&2
  usage
  exit 1
fi
if [[ ! -f "$DUMP_FILE" ]]; then
  echo "ERROR: dump file not found: $DUMP_FILE" >&2
  exit 1
fi

# --- Load .env (same tolerant KEY=value parsing install-quadlets.sh uses) ---
declare -A ENVVALS
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
    ENVVALS["$key"]="$val"
  done < "$ENV_FILE"
fi

POSTGRES_USER="${ENVVALS[POSTGRES_USER]:-fcculs}"
POSTGRES_DB="${DB_NAME_OVERRIDE:-${ENVVALS[POSTGRES_DB]:-fcculs}}"
POSTGRES_CONTAINER="${FCCULS_BACKUP_POSTGRES_CONTAINER:-${ENVVALS[BACKUP_POSTGRES_CONTAINER]:-postgres}}"

echo "Target container: $POSTGRES_CONTAINER"
echo "Target database:  $POSTGRES_DB$( [[ -n "$DB_NAME_OVERRIDE" ]] && echo ' (override via --db-name)' )"
echo "Dump file:         $DUMP_FILE"
echo ""
echo "THIS WILL DROP AND RECREATE EVERY OBJECT IN '$POSTGRES_DB' ON CONTAINER '$POSTGRES_CONTAINER'"
echo "BEFORE LOADING THE DUMP. This cannot be undone."

if [[ "$CONFIRM" -ne 1 ]]; then
  echo ""
  echo "Refusing to proceed without --confirm (dry run only). Re-run with --confirm to actually restore."
  exit 1
fi

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: podman is required." >&2
  exit 1
fi
if ! podman container exists "$POSTGRES_CONTAINER"; then
  echo "ERROR: container '$POSTGRES_CONTAINER' not found. Is the stack running?" >&2
  exit 1
fi

# If restoring into a database other than the one that already exists
# (e.g. a disposable verification database), create it first -- `createdb`
# is a no-op failure (not fatal) if it already exists.
if [[ -n "$DB_NAME_OVERRIDE" ]]; then
  echo "Ensuring database '$POSTGRES_DB' exists (creating if needed)..."
  podman exec "$POSTGRES_CONTAINER" createdb -U "$POSTGRES_USER" "$POSTGRES_DB" 2>/dev/null || true
fi

echo "Dropping and recreating the 'public' schema in '$POSTGRES_DB'..."
podman exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

echo "Restoring $DUMP_FILE into '$POSTGRES_DB'..."
gunzip -c "$DUMP_FILE" | podman exec -i "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1

echo ""
echo "Restore complete. Row count sanity check:"
podman exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  SELECT schemaname, relname AS table_name, n_live_tup AS approx_row_count
  FROM pg_stat_user_tables
  ORDER BY relname;
"
