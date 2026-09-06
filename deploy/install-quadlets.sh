#!/usr/bin/env bash
# Installs FCC ULS Explorer's Podman Quadlet units into the current user's
# rootless systemd directory (~/.config/containers/systemd/), substituting
# the repo's .env values into the units, then reloads systemd and starts
# the stack in dependency order.
#
# Idempotent: safe to re-run after editing a unit template or .env --
# changed units are re-rendered, systemd is reloaded, and running units
# whose unit file changed are restarted.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_DIR="$REPO_DIR/quadlet"
TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd"
ENV_FILE="$REPO_DIR/.env"

echo "Repo:       $REPO_DIR"
echo "Templates:  $TEMPLATE_DIR"
echo "Target:     $TARGET_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

# --- Load .env (tolerant KEY=value parsing, no quoting required) ---
declare -A ENVVALS
while IFS= read -r line || [[ -n "$line" ]]; do
  line="${line%$'\r'}"                       # tolerate CRLF
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
  key="${BASH_REMATCH[1]}"
  val="${BASH_REMATCH[2]}"
  # strip surrounding single/double quotes if present
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  ENVVALS["$key"]="$val"
done < "$ENV_FILE"

# Apply the same defaults compose.yaml uses.
POSTGRES_USER="${ENVVALS[POSTGRES_USER]:-fcculs}"
POSTGRES_DB="${ENVVALS[POSTGRES_DB]:-fcculs}"
POSTGRES_PASSWORD="${ENVVALS[POSTGRES_PASSWORD]:-}"
SESSION_SECRET="${ENVVALS[SESSION_SECRET]:-}"
PUBLIC_BASE_URL="${ENVVALS[PUBLIC_BASE_URL]:-http://localhost:8080}"
TRUST_REQUEST_HOST="${ENVVALS[TRUST_REQUEST_HOST]:-true}"
CORS_ALLOW_ORIGINS="${ENVVALS[CORS_ALLOW_ORIGINS]:-https://fcculs-explorer.n00tz.net}"
PUBLISHED_PORT="${ENVVALS[PUBLISHED_PORT]:-8080}"
SMTP_HOST="${ENVVALS[SMTP_HOST]:-localhost}"
SMTP_PORT="${ENVVALS[SMTP_PORT]:-587}"
SMTP_USER="${ENVVALS[SMTP_USER]:-}"
SMTP_PASSWORD="${ENVVALS[SMTP_PASSWORD]:-}"
SMTP_USE_TLS="${ENVVALS[SMTP_USE_TLS]:-true}"
SMTP_FROM_ADDRESS="${ENVVALS[SMTP_FROM_ADDRESS]:-no-reply@fcculs-explorer.example}"
INGEST_CRON_HOUR="${ENVVALS[INGEST_CRON_HOUR]:-7}"
INGEST_CRON_MINUTE="${ENVVALS[INGEST_CRON_MINUTE]:-0}"
MAX_DELIVERY_ATTEMPTS="${ENVVALS[MAX_DELIVERY_ATTEMPTS]:-5}"
DISPATCH_INTERVAL_SECONDS="${ENVVALS[DISPATCH_INTERVAL_SECONDS]:-60}"
QUEUE_NAME="${ENVVALS[QUEUE_NAME]:-fcculs-notifications}"

# Images: Quadlet can't `build:` like Compose, so point at locally built
# images (build them first -- see README's Quadlet section) unless
# overridden in .env.
API_IMAGE="${ENVVALS[API_IMAGE]:-localhost/fcculs-api:latest}"
INGESTOR_IMAGE="${ENVVALS[INGESTOR_IMAGE]:-localhost/fcculs-ingestor:latest}"
NOTIFIER_IMAGE="${ENVVALS[NOTIFIER_IMAGE]:-localhost/fcculs-notifier:latest}"
WEB_IMAGE="${ENVVALS[WEB_IMAGE]:-localhost/fcculs-web:latest}"

# Enforce the same "no hardcoded secrets" rule compose.yaml enforces via
# ${VAR:?...}: refuse to install with placeholder/missing secrets.
for required in POSTGRES_PASSWORD SESSION_SECRET; do
  val="${!required}"
  if [[ -z "$val" || "$val" == change-me* ]]; then
    echo "ERROR: $required is unset or still a placeholder in $ENV_FILE." >&2
    exit 1
  fi
done

# --- Render templates -> target dir ---
mkdir -p "$TARGET_DIR"

render() { # render <template-file> <output-file>
  local src="$1" dst="$2" content
  content="$(cat "$src")"
  # Order matters for values containing the delimiter; use %TOKEN% style.
  content="${content//%REPO_DIR%/$REPO_DIR}"
  content="${content//%POSTGRES_USER%/$POSTGRES_USER}"
  content="${content//%POSTGRES_PASSWORD%/$POSTGRES_PASSWORD}"
  content="${content//%POSTGRES_DB%/$POSTGRES_DB}"
  content="${content//%SESSION_SECRET%/$SESSION_SECRET}"
  content="${content//%PUBLIC_BASE_URL%/$PUBLIC_BASE_URL}"
  content="${content//%TRUST_REQUEST_HOST%/$TRUST_REQUEST_HOST}"
  content="${content//%CORS_ALLOW_ORIGINS%/$CORS_ALLOW_ORIGINS}"
  content="${content//%PUBLISHED_PORT%/$PUBLISHED_PORT}"
  content="${content//%SMTP_HOST%/$SMTP_HOST}"
  content="${content//%SMTP_PORT%/$SMTP_PORT}"
  content="${content//%SMTP_USER%/$SMTP_USER}"
  content="${content//%SMTP_PASSWORD%/$SMTP_PASSWORD}"
  content="${content//%SMTP_USE_TLS%/$SMTP_USE_TLS}"
  content="${content//%SMTP_FROM_ADDRESS%/$SMTP_FROM_ADDRESS}"
  content="${content//%INGEST_CRON_HOUR%/$INGEST_CRON_HOUR}"
  content="${content//%INGEST_CRON_MINUTE%/$INGEST_CRON_MINUTE}"
  content="${content//%MAX_DELIVERY_ATTEMPTS%/$MAX_DELIVERY_ATTEMPTS}"
  content="${content//%DISPATCH_INTERVAL_SECONDS%/$DISPATCH_INTERVAL_SECONDS}"
  content="${content//%QUEUE_NAME%/$QUEUE_NAME}"
  content="${content//%API_IMAGE%/$API_IMAGE}"
  content="${content//%INGESTOR_IMAGE%/$INGESTOR_IMAGE}"
  content="${content//%NOTIFIER_IMAGE%/$NOTIFIER_IMAGE}"
  content="${content//%WEB_IMAGE%/$WEB_IMAGE}"
  printf '%s\n' "$content" > "$dst"
}

for tmpl in "$TEMPLATE_DIR"/*; do
  render "$tmpl" "$TARGET_DIR/$(basename "$tmpl")"
  echo "rendered $(basename "$tmpl")"
done

# --- Reload systemd, which auto-generates native units from Quadlets ---
systemctl --user daemon-reload

# --- Linger check (required for the stack to survive logout/reboot) ---
linger_state="$(loginctl show-user "$USER" -p Linger 2>/dev/null | cut -d= -f2 || echo unknown)"
if [[ "$linger_state" != "yes" ]]; then
  echo ""
  echo "WARNING: lingering is NOT enabled for $USER -- these units will stop when you log out."
  echo "         Enable it (persists the user manager across logout/reboot) with:"
  echo "             loginctl enable-linger $USER"
  echo ""
else
  echo "linger: enabled for $USER"
fi

# --- Start in dependency order ---
# Network + volumes first, then infra, then the oneshot migrate (dependents
# will block on it via Requires=/After=), then apps, then web.
systemctl --user start fcculs-network.service
systemctl --user start pgdata-volume.service redisdata-volume.service
systemctl --user start fcculs-postgres.service fcculs-redis.service
systemctl --user start fcculs-migrate.service   # oneshot; blocks until migrations applied
systemctl --user start fcculs-api.service fcculs-ingestor.service \
                       fcculs-notifier-worker.service fcculs-notifier-dispatch.service
systemctl --user start fcculs-web.service

# fcculs-bootstrap.service is intentionally NOT started here -- it is a
# manual-start oneshot for the first-time full data load:
#     systemctl --user start fcculs-bootstrap.service

echo ""
echo "Done. Status:  systemctl --user status fcculs-api.service  (etc.)"
echo "Logs:          journalctl --user -u fcculs-api.service -f  (etc.)"
echo "One-time full data load on a fresh database:"
echo "               systemctl --user start fcculs-bootstrap.service"
