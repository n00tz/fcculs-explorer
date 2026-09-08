#!/bin/bash
set -e

echo "=== Cleaning up any previous test resources ==="
podman pod rm -f fcculs-itest 2>/dev/null || true

echo "=== Creating pod ==="
podman pod create --name fcculs-itest -p 15433:5432

echo "=== Starting Postgres ==="
podman run -d --pod fcculs-itest --name fcculs-itest-pg \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fcculs_test \
  docker.io/library/postgres:16-alpine

echo "=== Waiting for Postgres to be ready ==="
for i in $(seq 1 30); do
  if podman exec fcculs-itest-pg pg_isready -U postgres >/dev/null 2>&1; then
    echo "Postgres ready after ${i}s"
    break
  fi
  sleep 1
done

echo "=== Applying migrations ==="
podman cp /tmp/ingestor_full/002_fcc_raw_tables.sql fcculs-itest-pg:/tmp/
podman cp /tmp/ingestor_full/001_app_tables.sql fcculs-itest-pg:/tmp/
podman cp /tmp/ingestor_full/003_identity_grouping_views.sql fcculs-itest-pg:/tmp/
podman cp /tmp/005_frn_watch_support.sql fcculs-itest-pg:/tmp/
podman cp /tmp/006_new_operator_celebration.sql fcculs-itest-pg:/tmp/
podman cp /tmp/007_ingest_run_tracking.sql fcculs-itest-pg:/tmp/
podman cp /tmp/008_personal_radio_services.sql fcculs-itest-pg:/tmp/
podman cp /tmp/009_identity_views_all_services.sql fcculs-itest-pg:/tmp/
podman cp /tmp/010_ingest_polling.sql fcculs-itest-pg:/tmp/
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/002_fcc_raw_tables.sql
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/001_app_tables.sql
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/003_identity_grouping_views.sql
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/005_frn_watch_support.sql
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/006_new_operator_celebration.sql
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/007_ingest_run_tracking.sql
# 008 adds the personal-radio-service tables AND change_events.service, which
# ingest.py writes on every event -- without it the very first daily load here
# fails on an undefined column.
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/008_personal_radio_services.sql
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/009_identity_views_all_services.sql
# 010 adds complete_dumps, which the poller writes to when it notices a new
# weekly snapshot (see check_complete_dump_observation in integration_test.py).
podman exec fcculs-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/010_ingest_polling.sql

echo "=== Running ingestor integration test in python:3.12-slim ==="
podman run --rm --pod fcculs-itest \
  -v /tmp/ingestor_full:/app:Z \
  -e DATABASE_URL=postgresql://postgres:test@localhost:5432/fcculs_test \
  docker.io/library/python:3.12-slim \
  bash -c "pip install --quiet 'psycopg[binary]' && python3 /app/tests/integration_test.py"

echo "=== Cleaning up ==="
podman pod rm -f fcculs-itest

echo "=== DONE ==="
