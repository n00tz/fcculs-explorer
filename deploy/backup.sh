#!/usr/bin/env bash
# Dumps the fcculs Postgres database to a timestamped, gzip-compressed file
# via `podman exec ... pg_dump` (no direct DB port exposure needed -- this
# works whether Postgres is reachable only on the internal `fcculs.network`
# or not at all from the host), and prunes dumps older than a configurable
# retention period.
#
# The ingested FCC data (amateur/tower/history tables) is fully
# re-downloadable from the FCC, but `users`, `watches`, and
# `notification_channels` (which can contain webhook URLs/tokens) exist
# only in this database -- a disk failure with no backup would lose them
# permanently with no recovery path. Intended to run daily via the
# fcculs-backup.timer Quadlet unit (see quadlet/fcculs-backup.timer /
# fcculs-backup.service and README's "Running with Podman Quadlets"
# section), but is a plain standalone script -- safe to run manually or
# from any other scheduler (cron, etc.) too.
#
# Idempotent/safe to re-run: each run writes a new, uniquely-timestamped
# file and never touches the live database (pg_dump is read-only).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"

# --- Load .env (same tolerant KEY=value parsing install-quadlets.sh uses) ---
declare -A ENVVALS
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"                       # tolerate CRLF
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
    ENVVALS["$key"]="$val"
  done < "$ENV_FILE"
fi

POSTGRES_USER="${ENVVALS[POSTGRES_USER]:-fcculs}"
POSTGRES_DB="${ENVVALS[POSTGRES_DB]:-fcculs}"

# ContainerName in quadlet/fcculs-postgres.container (and the `postgres`
# service in compose.yaml) is literally "postgres", not "fcculs-postgres" --
# only the systemd *unit* is named fcculs-postgres.service. Overridable in
# case an operator has renamed it.
POSTGRES_CONTAINER="${FCCULS_BACKUP_POSTGRES_CONTAINER:-${ENVVALS[BACKUP_POSTGRES_CONTAINER]:-postgres}}"

# Output directory + retention, following this project's FCCULS_-prefixed
# env var convention for operator-facing overrides. Also readable from
# .env (unprefixed, like BACKUP_DIR/BACKUP_RETENTION_DAYS below) so it can
# be set alongside every other deployment setting in one place; an actual
# FCCULS_-prefixed environment variable (e.g. set directly in the Quadlet
# timer's unit file or by a caller) takes precedence over .env.
BACKUP_DIR="${FCCULS_BACKUP_DIR:-${ENVVALS[BACKUP_DIR]:-$HOME/fcculs-backups}}"
BACKUP_RETENTION_DAYS="${FCCULS_BACKUP_RETENTION_DAYS:-${ENVVALS[BACKUP_RETENTION_DAYS]:-3}}"

# .env values pass through this script's own KEY=value parser (not the
# shell), so a leading "~" from .env (e.g. BACKUP_DIR=~/fcculs-backups)
# would otherwise be taken literally instead of expanded to $HOME.
BACKUP_DIR="${BACKUP_DIR/#\~/$HOME}"

if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: podman is required." >&2
  exit 1
fi

if ! podman container exists "$POSTGRES_CONTAINER"; then
  echo "ERROR: container '$POSTGRES_CONTAINER' not found. Is the stack running?" >&2
  echo "       (override the container name with FCCULS_BACKUP_POSTGRES_CONTAINER if you renamed it)" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"

TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
OUT_FILE="$BACKUP_DIR/fcculs-${POSTGRES_DB}-${TIMESTAMP}.sql.gz"
TMP_FILE="${OUT_FILE}.tmp"

echo "Backing up database '$POSTGRES_DB' from container '$POSTGRES_CONTAINER' to $OUT_FILE ..."

# pg_dump's own stderr flows straight to our stderr; only stdout (the dump)
# is piped to gzip. Write to a .tmp path first and rename on success so a
# crashed/killed run never leaves a half-written file at the final name for
# restore.sh (or a human) to mistake for a complete backup.
podman exec "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" --format=plain "$POSTGRES_DB" \
  | gzip > "$TMP_FILE"

if [[ ! -s "$TMP_FILE" ]]; then
  echo "ERROR: backup produced an empty file; not keeping it." >&2
  rm -f "$TMP_FILE"
  exit 1
fi

mv "$TMP_FILE" "$OUT_FILE"
echo "Backup complete: $OUT_FILE ($(du -h "$OUT_FILE" | cut -f1))"

# --- Prune old backups ---
echo "Pruning backups older than $BACKUP_RETENTION_DAYS day(s) in $BACKUP_DIR ..."
deleted=0
while IFS= read -r -d '' old_file; do
  echo "  removing $old_file"
  rm -f "$old_file"
  deleted=$((deleted + 1))
done < <(find "$BACKUP_DIR" -maxdepth 1 -name 'fcculs-*.sql.gz' -mtime "+${BACKUP_RETENTION_DAYS}" -print0)
echo "Pruned $deleted old backup(s)."
