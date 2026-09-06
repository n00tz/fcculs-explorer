#!/usr/bin/env bash
# Stops and removes the FCC ULS Explorer Quadlet units installed by
# install-quadlets.sh. Does NOT remove the named volumes (pgdata /
# redisdata) or any built images by default -- pass --volumes to also
# delete the data volumes (DESTRUCTIVE), and/or --images to delete the
# locally built application images.
set -euo pipefail

TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd"

REMOVE_VOLUMES=0
REMOVE_IMAGES=0
for arg in "$@"; do
  case "$arg" in
    --volumes) REMOVE_VOLUMES=1 ;;
    --images)  REMOVE_IMAGES=1 ;;
    *) echo "Unknown option: $arg (supported: --volumes, --images)" >&2; exit 1 ;;
  esac
done

UNITS=(
  fcculs-web
  fcculs-api
  fcculs-ingestor
  fcculs-notifier-worker
  fcculs-notifier-dispatch
  fcculs-bootstrap
  fcculs-migrate
  fcculs-redis
  fcculs-postgres
  fcculs-network
  pgdata-volume
  redisdata-volume
)

echo "Stopping units..."
for name in "${UNITS[@]}"; do
  systemctl --user stop "$name.service" 2>/dev/null && echo "  stopped $name" || true
done

echo "Removing unit files from $TARGET_DIR..."
for f in fcculs.network pgdata.volume redisdata.volume \
         fcculs-postgres.container fcculs-redis.container fcculs-migrate.container \
         fcculs-api.container fcculs-ingestor.container fcculs-bootstrap.container \
         fcculs-notifier-worker.container fcculs-notifier-dispatch.container \
         fcculs-web.container; do
  rm -f "$TARGET_DIR/$f" && echo "  removed $f"
done

systemctl --user daemon-reload

if [[ "$REMOVE_VOLUMES" -eq 1 ]]; then
  echo "Removing named volumes (DESTRUCTIVE)..."
  podman volume rm pgdata redisdata 2>/dev/null || true
else
  echo "Kept named volumes pgdata and redisdata (use --volumes to delete them)."
fi

if [[ "$REMOVE_IMAGES" -eq 1 ]]; then
  echo "Removing locally built application images..."
  podman rmi localhost/fcculs-api:latest localhost/fcculs-ingestor:latest \
             localhost/fcculs-notifier:latest localhost/fcculs-web:latest 2>/dev/null || true
else
  echo "Kept locally built application images (use --images to delete them)."
fi

echo "Uninstall complete."
