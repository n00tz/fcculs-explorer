#!/bin/bash
set -euo pipefail

echo "=== Cleaning up any prior pod ==="
podman pod rm -f fcculs-smoke 2>/dev/null || true

echo "=== Creating pod with published ports ==="
podman pod create --name fcculs-smoke -p 18000:8000 -p 18080:8080

echo "=== Starting postgres ==="
podman run -d --pod fcculs-smoke --name smoke-pg \
  -e POSTGRES_USER=fcculs -e POSTGRES_PASSWORD=fcculs -e POSTGRES_DB=fcculs \
  docker.io/library/postgres:16-alpine

echo "=== Starting redis ==="
podman run -d --pod fcculs-smoke --name smoke-redis docker.io/library/redis:7-alpine

echo "=== Waiting for postgres ==="
for i in $(seq 1 30); do
  if podman exec smoke-pg pg_isready -U fcculs >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "=== Applying migrations ==="
for f in /tmp/build_ctx/migrations/*.sql; do
  echo "-- applying $f"
  podman exec -i smoke-pg psql -U fcculs -d fcculs < "$f"
done

echo "=== Starting api container ==="
podman run -d --pod fcculs-smoke --name smoke-api \
  -e FCCULS_DATABASE_URL="postgresql://fcculs:fcculs@127.0.0.1:5432/fcculs" \
  -e FCCULS_SESSION_SECRET="smoketestsecret" \
  -e FCCULS_SMTP_HOST="127.0.0.1" -e FCCULS_SMTP_PORT="2525" -e FCCULS_SMTP_USE_TLS="false" \
  -e FCCULS_MAGIC_LINK_BASE_URL="http://127.0.0.1:18080" \
  fcculs-api:test

echo "=== Starting notifier worker (just to confirm it boots and connects) ==="
podman run -d --pod fcculs-smoke --name smoke-notifier-worker \
  -e FCCULS_DATABASE_URL="postgresql://fcculs:fcculs@127.0.0.1:5432/fcculs" \
  -e FCCULS_REDIS_URL="redis://127.0.0.1:6379/0" \
  fcculs-notifier:test

echo "=== Starting web container ==="
podman run -d --pod fcculs-smoke --name smoke-web fcculs-web:test

sleep 5

echo "=== Container statuses ==="
podman ps -a --filter "pod=fcculs-smoke" --format "{{.Names}}: {{.Status}}"

echo "=== api logs ==="
podman logs smoke-api 2>&1 | tail -20

echo "=== notifier worker logs ==="
podman logs smoke-notifier-worker 2>&1 | tail -20

echo "=== web logs ==="
podman logs smoke-web 2>&1 | tail -20

echo "=== curl api docs ==="
curl -sS -o /dev/null -w "api /docs HTTP %{http_code}\n" http://127.0.0.1:18000/docs || echo "api curl FAILED"

echo "=== curl api openapi ==="
curl -sS -o /dev/null -w "api /openapi.json HTTP %{http_code}\n" http://127.0.0.1:18000/openapi.json || echo "api curl FAILED"

echo "=== curl web root ==="
curl -sS -o /dev/null -w "web / HTTP %{http_code}\n" http://127.0.0.1:18080/ || echo "web curl FAILED"

echo "=== curl web -> api proxy passthrough ==="
curl -sS -o /dev/null -w "web /api/openapi.json HTTP %{http_code}\n" http://127.0.0.1:18080/api/openapi.json || echo "web api-proxy curl FAILED"

echo "=== DONE ==="
