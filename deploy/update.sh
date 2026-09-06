#!/usr/bin/env bash
# Pulls the latest commit, rebuilds every application image (api, ingestor,
# notifier, web), and restarts the Quadlet-managed systemd units so the
# rebuilt images take effect immediately.
#
# This is the "one command to deploy the latest commit" entry point for the
# Quadlet path: an operator with nothing but a clone of this repo and a
# working rootless-Podman + Quadlet install (see the "Running with Podman
# Quadlets" README section) can run this after every `git push` to pick up
# code changes, with no manual `podman build`/`systemctl restart` steps.
#
# Every rebuilt image is tagged BOTH `:latest` (what the Quadlet units
# reference, so `systemctl --user restart` immediately uses the new build)
# and `:<short-commit-sha>` (an immutable, addressable tag for rollback --
# see "Rolling back" below), and carries an
# `org.opencontainers.image.revision` label set to the full commit hash so
# `podman inspect` can always answer "what commit is this image running?"
# even after the moving `:latest`/short-sha tags have been overwritten by a
# later build.
#
# Idempotent: safe to re-run. If the repo is already at the latest commit
# and images already carry that commit's revision label, it skips the
# rebuild (use --force to rebuild anyway, e.g. after a local Dockerfile-only
# edit that didn't change the app code).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

FORCE=0
NO_PULL=0
NO_RESTART=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --no-pull) NO_PULL=1 ;;
    --no-restart) NO_RESTART=1 ;;
    -h|--help)
      cat <<'USAGE'
Usage: deploy/update.sh [--force] [--no-pull] [--no-restart]

  --force       Rebuild images even if HEAD didn't move (e.g. after editing
                a Dockerfile without an app-code commit).
  --no-pull     Skip `git pull`; rebuild/deploy whatever is already checked
                out (useful for testing a local, uncommitted change).
  --no-restart  Build and label the images but don't touch systemd units
                (useful if you manage restarts yourself, or use Compose).
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $arg (see --help)" >&2
      exit 1
      ;;
  esac
done

# --- Load images to build/tag from .env (same overrides install-quadlets.sh
#     honors), falling back to the documented defaults. ---
ENV_FILE="$REPO_DIR/.env"
declare -A ENVVALS
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"; val="${BASH_REMATCH[2]}"
    val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
    ENVVALS["$key"]="$val"
  done < "$ENV_FILE"
fi
API_IMAGE="${ENVVALS[API_IMAGE]:-localhost/fcculs-api:latest}"
INGESTOR_IMAGE="${ENVVALS[INGESTOR_IMAGE]:-localhost/fcculs-ingestor:latest}"
NOTIFIER_IMAGE="${ENVVALS[NOTIFIER_IMAGE]:-localhost/fcculs-notifier:latest}"
WEB_IMAGE="${ENVVALS[WEB_IMAGE]:-localhost/fcculs-web:latest}"
# Strip a trailing ":latest" (or any tag) so we can append our own tags below.
img_repo() { echo "${1%:*}"; }

if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is required." >&2
  exit 1
fi
if ! command -v podman >/dev/null 2>&1; then
  echo "ERROR: podman is required." >&2
  exit 1
fi

BEFORE_SHA="$(git rev-parse HEAD)"

if [[ "$NO_PULL" -eq 0 ]]; then
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "ERROR: working tree has uncommitted changes; commit/stash them or re-run with --no-pull." >&2
    exit 1
  fi
  echo "Pulling latest changes (fast-forward only)..."
  git pull --ff-only
else
  echo "Skipping git pull (--no-pull)."
fi

AFTER_SHA="$(git rev-parse HEAD)"
SHORT_SHA="$(git rev-parse --short HEAD)"
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

if [[ "$FORCE" -eq 0 && "$BEFORE_SHA" == "$AFTER_SHA" ]]; then
  # Nothing new pulled -- but only skip the rebuild if the currently tagged
  # `:latest` api image (used as a proxy for "did we already build this
  # commit") already carries this exact commit's revision label.
  existing_rev="$(podman image inspect --format '{{ index .Labels "org.opencontainers.image.revision" }}' "$API_IMAGE" 2>/dev/null || true)"
  if [[ "$existing_rev" == "$AFTER_SHA" ]]; then
    echo "Already up to date at $SHORT_SHA and images already built from it. Nothing to do (use --force to rebuild anyway)."
    exit 0
  fi
fi

echo "Building images from commit $AFTER_SHA ($SHORT_SHA)..."

build_image() { # build_image <context-dir> <image-ref>
  local context="$1" image_ref="$2" repo
  repo="$(img_repo "$image_ref")"
  echo "--- building $repo (context: $context) ---"
  podman build \
    --label "org.opencontainers.image.revision=$AFTER_SHA" \
    --label "org.opencontainers.image.version=$SHORT_SHA" \
    --label "org.opencontainers.image.created=$BUILD_DATE" \
    --label "org.opencontainers.image.source=$(git config --get remote.origin.url 2>/dev/null || echo unknown)" \
    -t "${repo}:latest" \
    -t "${repo}:${SHORT_SHA}" \
    "$context"
}

build_image "$REPO_DIR/api"      "$API_IMAGE"
build_image "$REPO_DIR/ingestor" "$INGESTOR_IMAGE"
build_image "$REPO_DIR/notifier" "$NOTIFIER_IMAGE"
build_image "$REPO_DIR/web"      "$WEB_IMAGE"

echo ""
echo "Built and tagged (per image): :latest, :$SHORT_SHA"
echo "Label org.opencontainers.image.revision=$AFTER_SHA is set on every image."

if [[ "$NO_RESTART" -eq 1 ]]; then
  echo "Skipping unit restarts (--no-restart). Images are built; restart units yourself when ready."
  exit 0
fi

if ! systemctl --user list-unit-files fcculs-api.service >/dev/null 2>&1; then
  echo ""
  echo "No Quadlet units installed yet -- run 'bash deploy/install-quadlets.sh' first,"
  echo "or if you're on the Compose path, run: podman compose up -d"
  exit 0
fi

echo ""
echo "Restarting Quadlet-managed units so the rebuilt :latest images take effect..."
# migrate first (oneshot, RemainAfterExit): re-running is safe/idempotent
# (db/*.sql all use IF NOT EXISTS / DO $$ IF NOT EXISTS guards) and picks up
# any new migrations added in this pull before the apps that depend on them
# restart.
systemctl --user restart fcculs-migrate.service
systemctl --user restart fcculs-api.service
systemctl --user restart fcculs-ingestor.service
systemctl --user restart fcculs-notifier-worker.service
systemctl --user restart fcculs-notifier-dispatch.service
systemctl --user restart fcculs-web.service

echo ""
echo "Restart complete. Quick status check:"
systemctl --user is-active fcculs-migrate.service fcculs-api.service fcculs-ingestor.service \
  fcculs-notifier-worker.service fcculs-notifier-dispatch.service fcculs-web.service || true
echo ""
echo "Verify: curl http://localhost:\${PUBLISHED_PORT:-8080}/"
echo "Rollback if needed: re-tag a prior commit's image, e.g."
echo "  podman tag ${API_IMAGE%:*}:<old-short-sha> ${API_IMAGE%:*}:latest && systemctl --user restart fcculs-api.service"
