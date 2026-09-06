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
podman cp /tmp/api_full/../ingestor_full/002_fcc_raw_tables.sql fcculs-api-itest-pg:/tmp/ 2>/dev/null || \
  podman cp /tmp/ingestor_full/002_fcc_raw_tables.sql fcculs-api-itest-pg:/tmp/
podman cp /tmp/ingestor_full/001_app_tables.sql fcculs-api-itest-pg:/tmp/
podman cp /tmp/ingestor_full/003_identity_grouping_views.sql fcculs-api-itest-pg:/tmp/
podman exec fcculs-api-itest-pg psql -U postgres -d fcculs_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
podman exec fcculs-api-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/002_fcc_raw_tables.sql
podman exec fcculs-api-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/001_app_tables.sql
podman exec fcculs-api-itest-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 -f /tmp/003_identity_grouping_views.sql

echo "=== Running API unit + integration tests in python:3.12-slim ==="
podman run --rm --pod fcculs-api-itest \
  -v /tmp/api_full:/app:Z \
  -e FCCULS_DATABASE_URL=postgresql://postgres:test@localhost:5432/fcculs_test \
  -e FCCULS_REDIS_URL=redis://localhost:6379/0 \
  docker.io/library/python:3.12-slim \
  bash -c "pip install --quiet -r /app/requirements.txt && cd /app && python3 -m pytest tests/test_security.py tests/test_mailer.py tests/test_auth_base_url.py tests/test_admin_auth.py tests/test_url_safety.py -v && python3 tests/integration_test.py"

# tests/real_smtp_smoke_test.py is a real-SMTP-listener smoke test (not
# auto-run here, same as integration_test.py's real-Postgres model): it
# needs a live SMTP listener reachable via FCCULS_SMTP_HOST/FCCULS_SMTP_PORT
# and is meant to be run manually with `python3 tests/real_smtp_smoke_test.py`
# against a disposable listener when validating SMTP-related changes.

echo "=== Cleaning up ==="
podman pod rm -f fcculs-api-itest

echo "=== DONE ==="
