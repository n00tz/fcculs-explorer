#!/bin/sh
# Applied inside the migrate container. Waits for Postgres to accept
# connections, then applies every /migrations/*.sql file in order.
set -eu

: "${POSTGRES_USER:?set POSTGRES_USER}"
: "${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}"
: "${POSTGRES_DB:?set POSTGRES_DB}"

export PGPASSWORD="$POSTGRES_PASSWORD"

echo "waiting for postgres..."
tries=0
until pg_isready -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q; do
  tries=$((tries + 1))
  if [ "$tries" -ge 60 ]; then
    echo "postgres never became ready" >&2
    exit 1
  fi
  sleep 1
done
echo "postgres is ready, applying migrations"

# Postgres can briefly disappear from the network DNS while its container
# is being recreated (e.g. systemctl restart of the postgres unit), so
# retry the whole migration pass on transient connection/DNS failures.
attempt=0
until [ "$attempt" -ge 10 ]; do
  attempt=$((attempt + 1))
  ok=1
  for f in /migrations/*.sql; do
    echo "applying $f"
    if ! psql -v ON_ERROR_STOP=1 -h postgres -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f "$f"; then
      ok=0
      break
    fi
  done
  if [ "$ok" -eq 1 ]; then
    echo "all migrations applied"
    exit 0
  fi
  echo "migration attempt $attempt failed, retrying in 3s..."
  sleep 3
done

echo "migrations did not complete after 10 attempts" >&2
exit 1
