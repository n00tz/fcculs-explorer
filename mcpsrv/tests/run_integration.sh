#!/bin/bash
set -e

# Integration test for the MCP server. Stands up the full real chain --
# Postgres + Redis + the api service + the MCP server -- and drives it with
# a real MCP client over streamable HTTP. Nothing is mocked, matching this
# project's testing convention for every other service.
#
# Expects these staged on the host first:
#   /tmp/mcpsrv_full    <- mcpsrv/ (app, tests, requirements.txt)
#   /tmp/api_full       <- api/ (app, tests, requirements.txt)
#   /tmp/db_migrations  <- db/*.sql

POD=fcculs-mcp-itest

echo "=== Cleaning up any previous test resources ==="
podman pod rm -f $POD 2>/dev/null || true

echo "=== Creating pod ==="
podman pod create --name $POD

echo "=== Starting Postgres ==="
podman run -d --pod $POD --name $POD-pg \
  -e POSTGRES_PASSWORD=test -e POSTGRES_DB=fcculs_test \
  docker.io/library/postgres:16-alpine

echo "=== Starting Redis ==="
podman run -d --pod $POD --name $POD-redis docker.io/library/redis:7-alpine

echo "=== Waiting for Postgres ==="
for i in $(seq 1 30); do
  podman exec $POD-pg pg_isready -U postgres >/dev/null 2>&1 && { echo "ready after ${i}s"; break; }
  sleep 1
done

echo "=== Waiting for Redis ==="
for i in $(seq 1 30); do
  podman exec $POD-redis redis-cli ping >/dev/null 2>&1 && { echo "ready after ${i}s"; break; }
  sleep 1
done

echo "=== Applying migrations ==="
podman cp /tmp/db_migrations $POD-pg:/tmp/db_migrations
podman exec $POD-pg psql -U postgres -d fcculs_test -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
for migration in $(ls /tmp/db_migrations/*.sql | sort); do
  name=$(basename "$migration")
  echo "--- applying $name"
  podman exec $POD-pg psql -U postgres -d fcculs_test -v ON_ERROR_STOP=1 \
    -f "/tmp/db_migrations/$name"
done

echo "=== Seeding data ==="
# Reuse the api integration test's own seed SQL rather than maintaining a
# second copy that could drift out of sync with the schema. That module
# imports the api app, so it needs the api's full requirements.
podman run --rm --pod $POD -v /tmp/api_full:/app:Z \
  -e FCCULS_DATABASE_URL=postgresql://postgres:test@localhost:5432/fcculs_test \
  -e FCCULS_SESSION_SECRET=test-secret \
  -w /app \
  docker.io/library/python:3.14-slim \
  bash -c "pip install --quiet -r requirements.txt && python3 -c \"
import sys; sys.path.insert(0, '/app')
import tests.integration_test as it
it.seed_database()
print('seeded')
\""

echo "=== Starting the api service ==="
podman run -d --pod $POD --name $POD-api -v /tmp/api_full:/app:Z \
  -e FCCULS_DATABASE_URL=postgresql://postgres:test@localhost:5432/fcculs_test \
  -e FCCULS_REDIS_URL=redis://localhost:6379/0 \
  -e FCCULS_SESSION_SECRET=test-secret \
  -w /app \
  docker.io/library/python:3.14-slim \
  bash -c "pip install --quiet -r requirements.txt && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo "=== Waiting for the api to answer ==="
for i in $(seq 1 90); do
  if podman exec $POD-api python3 -c "
import urllib.request
urllib.request.urlopen('http://localhost:8000/api/field-definitions', timeout=2)
" >/dev/null 2>&1; then
    echo "api ready after ${i}s"
    break
  fi
  if [ "$i" = "90" ]; then
    echo "!!! api never became ready; logs:"; podman logs $POD-api | tail -40; exit 1
  fi
  sleep 1
done

echo "=== Building the MCP server image ==="
podman build -t localhost/fcculs-mcp:itest /tmp/mcpsrv_full

echo "=== Starting the MCP server ==="
podman run -d --pod $POD --name $POD-mcp \
  -e FCCULS_API_BASE_URL=http://localhost:8000 \
  -e FCCULS_MCP_PORT=8080 \
  localhost/fcculs-mcp:itest

echo "=== Waiting for the MCP server ==="
for i in $(seq 1 60); do
  # Any HTTP status proves it's listening and routing: a bare GET is not a
  # valid MCP request, so 400/406 are success signals here, not failures.
  if podman exec $POD-mcp python3 -c "
import urllib.error, urllib.request
try:
    urllib.request.urlopen('http://localhost:8080/mcp', timeout=2)
except urllib.error.HTTPError:
    pass
" >/dev/null 2>&1; then
    echo "mcp server responding after ${i}s"
    break
  fi
  if [ "$i" = "60" ]; then
    echo "!!! mcp server never came up; logs:"; podman logs $POD-mcp | tail -40; exit 1
  fi
  sleep 1
done

echo "=== Running MCP unit tests ==="
podman run --rm -v /tmp/mcpsrv_full:/src:Z localhost/fcculs-mcp:itest bash -c "
  pip install --quiet pytest >/dev/null 2>&1
  mkdir -p /tmp/run && cp -r /app/app /src/tests /tmp/run/
  cd /tmp/run && python -m pytest tests/test_tools.py -v -p no:cacheprovider"

echo "=== Running MCP integration test (real MCP client over HTTP) ==="
podman run --rm --pod $POD -v /tmp/mcpsrv_full:/src:Z \
  -e MCP_TEST_URL=http://localhost:8080/mcp \
  localhost/fcculs-mcp:itest bash -c "
  mkdir -p /tmp/run && cp -r /app/app /src/tests /tmp/run/
  cd /tmp/run && python tests/integration_test.py"

echo "=== MCP server logs (tail) ==="
podman logs $POD-mcp 2>&1 | tail -15

echo "=== Cleaning up ==="
podman pod rm -f $POD

echo "=== DONE ==="
