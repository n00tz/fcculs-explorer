#!/bin/bash
set -e

echo "=== Cleaning up any previous test resources ==="
podman pod rm -f fcculs-api-itest 2>/dev/null || true

echo "=== Creating pod ==="
podman pod create --name fcculs-api-itest -p 15434:5432

echo "=== Starting Postgres ==="
podman run -d --pod fcculs-api-itest --name fcculs-api-itest-pg \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fcculs_test \
  docker.io/library/postgres:16-alpine

echo "=== Starting Redis (needed for rate-limiting on auth/admin-login) ==="
podman run -d --pod fcculs-api-itest --name fcculs-api-itest-redis \
  docker.io/library/redis:7-alpine

echo "=== Waiting for Postgres to be ready ==="
for i in $(seq 1 30); do
  if podman exec fcculs-api-itest-pg pg_isready -U postgres >/dev/null 2>&1; then
    echo "Postgres ready after ${i}s"
    break
  fi
  sleep 1
done

echo "=== Waiting for Redis to be ready ==="
for i in $(seq 1 30); do
  if podman exec fcculs-api-itest-redis redis-cli ping >/dev/null 2>&1; then
    echo "Redis ready after ${i}s"
    break
  fi
  sleep 1
done

echo "=== Applying migrations ==="
# Apply every migration in db/ in numeric order rather than a hardcoded list.
# The previous hardcoded list had already gone stale (it was missing 007), which
# would silently test against an out-of-date schema; globbing makes new
# migrations apply automatically.
podman cp /tmp/db_migrations fcculs-api-itest-pg:/tmp/db_migrations
podman exec fcculs-api-itest-pg psql -U postgres -d fcculs_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
for migration in $(ls /tmp/db_migrations/*.sql | sort); do
  name=$(basename "$migration")
  echo "--- applying $name"
  podman exec fcculs-api-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 \
    -f "/tmp/db_migrations/$name"
done

echo "=== Running API unit + integration tests in python:3.14-slim ==="
# Runtime matches api/Dockerfile (python:3.14-slim). This previously pinned
# 3.12 and had silently drifted after the base image was bumped, which meant
# tests were validating against a runtime production no longer uses.
podman run --rm --pod fcculs-api-itest \
  -v /tmp/api_full:/app:Z \
  -e FCCULS_DATABASE_URL=postgresql://postgres:test@localhost:5432/fcculs_test \
  -e FCCULS_REDIS_URL=redis://localhost:6379/0 \
  docker.io/library/python:3.14-slim \
  bash -c "pip install --quiet -r /app/requirements.txt && cd /app && python3 -m pytest tests/test_*.py -v && python3 tests/integration_test.py"

# tests/real_smtp_smoke_test.py is a real-SMTP-listener smoke test (not
# auto-run here, same as integration_test.py's real-Postgres model): it
# needs a live SMTP listener reachable via FCCULS_SMTP_HOST/FCCULS_SMTP_PORT
# and is meant to be run manually with `python3 tests/real_smtp_smoke_test.py`
# against a disposable listener when validating SMTP-related changes.

echo "=== Cleaning up ==="
podman pod rm -f fcculs-api-itest

echo "=== DONE ==="
