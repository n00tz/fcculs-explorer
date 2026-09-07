#!/bin/bash
set -e

echo "=== Cleaning up any previous test resources ==="
podman pod rm -f fcculs-notifier-itest 2>/dev/null || true

echo "=== Creating pod ==="
podman pod create --name fcculs-notifier-itest -p 15435:5432 -p 16380:6379

echo "=== Starting Postgres ==="
podman run -d --pod fcculs-notifier-itest --name fcculs-notifier-itest-pg \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fcculs_test \
  docker.io/library/postgres:16-alpine

echo "=== Starting Redis ==="
podman run -d --pod fcculs-notifier-itest --name fcculs-notifier-itest-redis \
  docker.io/library/redis:7-alpine

echo "=== Waiting for Postgres to be ready ==="
for i in $(seq 1 30); do
  if podman exec fcculs-notifier-itest-pg pg_isready -U postgres >/dev/null 2>&1; then
    echo "Postgres ready after ${i}s"
    break
  fi
  sleep 1
done

echo "=== Applying migrations ==="
# Apply every migration in db/ in numeric order rather than a hardcoded list,
# which had already gone stale here (it stopped at 005) and would silently
# test against an out-of-date schema.
podman cp /tmp/db_migrations fcculs-notifier-itest-pg:/tmp/db_migrations
podman exec fcculs-notifier-itest-pg psql -U postgres -d fcculs_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
for migration in $(ls /tmp/db_migrations/*.sql | sort); do
  name=$(basename "$migration")
  echo "--- applying $name"
  podman exec fcculs-notifier-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 \
    -f "/tmp/db_migrations/$name"
done

echo "=== Running notifier unit + integration tests in python:3.12-slim ==="
podman run --rm --pod fcculs-notifier-itest \
  -v /tmp/notifier_full:/app:Z \
  -e FCCULS_DATABASE_URL=postgresql://postgres:test@localhost:5432/fcculs_test \
  -e FCCULS_REDIS_URL=redis://localhost:6379/0 \
  docker.io/library/python:3.12-slim \
  bash -c "pip install --quiet -r /app/requirements.txt && cd /app && python3 -m unittest discover -s tests -p 'test_*.py' -v && python3 tests/integration_test.py"

echo "=== Cleaning up ==="
podman pod rm -f fcculs-notifier-itest

echo "=== DONE ==="
