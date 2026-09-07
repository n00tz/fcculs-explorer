# FCC ULS Explorer & Alerting Service

Self-hostable service for browsing FCC ULS Amateur Radio Service and Antenna
Structure Registration (Tower) data, with watch-based alerting (email,
email-to-SMS, or generic webhook) on changes to a specific callsign or ULS
ID. Built for a single rootless-Podman host, no paid third-party services
required.

## Status

Feature-complete for v1: ingestion, API, notifier, frontend, containerization,
and the Compose stack are all built and verified. See `docs/plan.md` for the
full design rationale and progress log.

**Looking to use the app (search, browse, filters, sign-in, watches/alerts)
rather than deploy or administer it? See `docs/user-guide.md`.**

## Stack

| Concern | Choice |
|---|---|
| API | Python 3.12 + FastAPI |
| Database | PostgreSQL 16 (`pg_trgm` search) |
| Cache/Queue | Redis 7 + RQ |
| Scheduler | APScheduler (inside the `ingestor` container) |
| Frontend | SvelteKit, static-adapter SPA build |
| Reverse proxy / static server | Caddy |
| Auth | Passwordless magic-link email, signed session cookies |
| Deployment | Rootless Podman + `podman compose` / `docker compose` |

## Repository Layout

```
api/        FastAPI backend: search, browse, detail, identity-grouping,
            auth, notification-channel and watch CRUD. api/Dockerfile
ingestor/   FCC file downloader, pipe-delimited parser, diff-before-upsert,
            change_events generation, APScheduler daily-cron entrypoint
            (scheduler.py). ingestor/Dockerfile
notifier/   RQ worker (app/worker.py) + dispatcher (app/dispatch.py) that
            match new change_events to active watches and deliver via SMTP,
            email-to-SMS gateways, or webhooks (ntfy/Discord/Telegram/Matrix
            presets included). Single image, two roles. notifier/Dockerfile
web/        SvelteKit frontend (static SPA) + Caddyfile + web/Dockerfile
            (multi-stage Node build -> Caddy runtime image)
db/         SQL migrations, applied in filename order by the `migrate`
            Compose service
deploy/     deploy/smoke_test.sh -- a scripted Podman-pod smoke test used
            to validate that built images actually start and respond
docs/       Implementation plan/progress log (plan.md) and the end-user
            guide (user-guide.md)
compose.yaml, .env.example   Compose stack definition (repo root)
```

## Data Sources

- FCC ULS Amateur Radio Service (`l_amat`): complete weekly dump + daily
  transaction files.
- FCC ULS Antenna Structure Registration (ASR / "Tower", `r_tower`):
  complete weekly dump + daily transaction files.

All source files are free, public, and unauthenticated under FCC's public
access program (no API key, no rate-limit registration). The ingestor
downloads directly from `data.fcc.gov`; see `docs/plan.md` §4 for the file
layout this project parses.

## Deploying

Prerequisites on the target host:

- Podman (rootless is fully supported and the tested configuration).
- A Compose provider Podman can shell out to. If `podman compose version`
  fails with "compose provider" errors, install the standalone
  [docker-compose v2 binary](https://github.com/docker/compose/releases)
  into `~/.docker/cli-plugins/docker-compose` (per-user, no root/system
  package needed) and enable the Podman API socket:
  `systemctl --user enable --now podman.socket`.
- An SMTP relay reachable from the host (for magic-link login emails and
  outbound alert emails/email-to-SMS). Any relay works — self-hosted
  Postfix, a mail provider's SMTP-relay product, etc.

Steps:

```bash
git clone <this repo> fcculs-explorer && cd fcculs-explorer
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD, SESSION_SECRET (generate with
# `python -c "import secrets; print(secrets.token_urlsafe(32))"`),
# PUBLIC_BASE_URL (how users will reach the web UI), and SMTP_* settings.

podman compose up -d --build
```

This starts, on the Compose default network: `postgres`, `redis`, a
one-shot `migrate` job (applies every file in `db/*.sql` in order; all
migrations are idempotent so it's safe to re-run on every `up`), `api`,
`ingestor` (runs on a daily cron by default), `notifier-worker` +
`notifier-dispatch` (one image, two roles), and `web` (the only service
that publishes a host port, default `8080`, see `PUBLISHED_PORT` in
`.env`).

### First-time data load

The `ingestor`'s default command runs the daily-cron scheduler, which
assumes tables are already populated. For a brand-new database, run a
one-off bootstrap load of the complete weekly dumps first:

```bash
podman compose run --rm ingestor python scheduler.py --bootstrap
```

After that completes, the regular `ingestor` service's daily cron
(`INGEST_CRON_HOUR`/`INGEST_CRON_MINUTE` in `.env`, default 07:00 UTC) keeps
data current via the daily transaction files.

### Verifying the stack

```bash
podman compose ps
curl -s http://localhost:8080/                      # web UI shell (200)
curl -s http://localhost:8080/api/search?q=W1AW      # proxied API call
```

`deploy/smoke_test.sh` is the scripted version of this check (built for a
disposable Podman pod, not the Compose stack itself) — useful as a
reference when validating a rebuilt image outside of Compose.

## Running with Podman Quadlets (systemd-managed)

An alternative, additive deployment path alongside the Compose stack:
instead of a running `podman compose` process, each service is a
systemd-managed container unit (Podman Quadlets), supervised by the user
manager. The stack survives reboots and host logouts (with lingering
enabled) with no extra tooling. Still single-host, still rootless.

### Prerequisites

- Rootless Podman 4.9+ (developed and verified against 4.9.3).
- Lingering enabled for your user, so the user systemd manager (and the
  stack) survives logout/reboot:
  `loginctl enable-linger $USER`
- The application images built locally — Quadlet has no `build:` directive,
  so build them from the repo root once (and after any code change):

  ```bash
  podman build -t localhost/fcculs-api:latest      ./api
  podman build -t localhost/fcculs-ingestor:latest ./ingestor
  podman build -t localhost/fcculs-notifier:latest ./notifier
  podman build -t localhost/fcculs-web:latest      ./web
  ```

  (Different image names/tags can be set via `API_IMAGE`,
  `INGESTOR_IMAGE`, `NOTIFIER_IMAGE`, `WEB_IMAGE` in `.env`.)
- A configured `.env` (same file as the Compose path; `cp .env.example
  .env` and fill in `POSTGRES_PASSWORD`, `SESSION_SECRET`, `SMTP_*`).

### Install / start the stack

```bash
bash deploy/install-quadlets.sh
```

The script renders `quadlet/*` into `~/.config/containers/systemd/`
(substituting your `.env` values — secrets are never committed into the
repo's unit templates), runs `systemctl --user daemon-reload`, warns if
lingering is disabled, and starts the units in dependency order. It is
idempotent: re-run it after editing a unit in `quadlet/` or changing
`.env`.

### Status, logs, restarts

```bash
systemctl --user status fcculs-api.service        # any unit
journalctl --user -u fcculs-api.service -f        # follow logs
systemctl --user restart fcculs-api.service       # restart one service
```

Unit names: `fcculs-network`, `pgdata-volume`, `redisdata-volume`,
`fcculs-postgres`, `fcculs-redis`, `fcculs-migrate` (oneshot), `fcculs-api`,
`fcculs-ingestor`, `fcculs-notifier-worker`, `fcculs-notifier-dispatch`,
`fcculs-web`. On the shared `fcculs` network, containers resolve each other
by their Compose-matching names (`postgres`, `redis`, `api`), so the
existing `Caddyfile` (`reverse_proxy api:8000`) works unchanged.

### First-time bootstrap load

`fcculs-bootstrap.service` is a manual-start oneshot unit (never
auto-started). On a fresh database:

```bash
systemctl --user start fcculs-bootstrap.service
journalctl --user -u fcculs-bootstrap.service -f   # watch progress
```

### Updating after a rebuild

For a one-off manual rebuild of a single service:

```bash
podman build -t localhost/fcculs-api:latest ./api   # rebuild what changed
systemctl --user restart fcculs-api.service         # restart just that unit
```

Or re-run `deploy/install-quadlets.sh` after editing unit templates.

**To deploy a new commit end-to-end** (the common case: you pushed a code
change and want it live), use `deploy/update.sh` instead of the manual steps
above:

```bash
bash deploy/update.sh
```

This pulls the latest commit (fast-forward only; it refuses to run over a
dirty working tree), rebuilds `api`, `ingestor`, `notifier`, and `web` from
that commit, and restarts `fcculs-migrate` (safe/idempotent to re-run) then
every app unit so the new `:latest` images take effect immediately —
Quadlet's systemd units always resolve `:latest` at container (re)start, so
restarting is all that's needed once the image has been rebuilt. Every
rebuilt image is tagged both `:latest` and `:<short-commit-sha>` (for
rollback) and carries an `org.opencontainers.image.revision` label with the
full commit hash, so `podman image inspect --format '{{ index .Labels
"org.opencontainers.image.revision" }}' localhost/fcculs-api:latest` always
tells you exactly what's deployed. It's idempotent: re-running when nothing
changed is a no-op (`--force` overrides). Useful flags: `--no-pull` (rebuild
whatever's checked out, e.g. to test an uncommitted change), `--no-restart`
(build/tag only). To roll back, re-tag an older `:<short-sha>` image as
`:latest` and restart that unit (the script prints the exact command at the
end of a run).

### Uninstall

```bash
bash deploy/uninstall-quadlets.sh            # stops/removes units; keeps data
bash deploy/uninstall-quadlets.sh --volumes  # also DELETES pgdata/redisdata
bash deploy/uninstall-quadlets.sh --images   # also deletes built images
```

### Differences from the Compose path

Both paths run the same images, same named volumes (`pgdata`, `redisdata` —
so you can migrate between them without losing data), and same `.env`. The
Quadlet path replaces Compose's orchestration with systemd: units start on
boot automatically (no `podman compose up` needed after a reboot), and each
service is supervised/restarted by systemd. The migration job is a
`Type=oneshot, RemainAfterExit=yes` unit; app units declare
`Requires=fcculs-migrate.service` + `After=fcculs-migrate.service` to
reproduce Compose's `depends_on: service_completed_successfully` gating.
One caveat: manually restarting `fcculs-migrate.service` will stop the
dependent app units (Requires propagation) — restart them afterward, or
just re-run `deploy/install-quadlets.sh`.


## Configuration Reference (`.env`)

| Variable | Used by | Purpose |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | postgres, migrate, api, ingestor, notifier | Database credentials |
| `SESSION_SECRET` | api | Signing key for session cookies (**required**, no default) |
| `PUBLIC_BASE_URL` | api | **Fallback only.** By default, magic-link emails use the actual Host/X-Forwarded-* headers of the request that triggered them (works automatically behind a reverse proxy or Cloudflare Tunnel); this is used only if `TRUST_REQUEST_HOST=false` or a request has no Host header |
| `TRUST_REQUEST_HOST` | api | Set to `false` to always use `PUBLIC_BASE_URL` instead of deriving the base URL from request headers (default `true`) |
| `PUBLISHED_PORT` | web | Host port the Caddy/web container is published on |
| `CORS_ALLOW_ORIGINS` | api | Comma-separated list of origins allowed to make credentialed (cookie-carrying) cross-origin requests to the API. **Must be the real public hostname(s) users reach the app at** (e.g. your Cloudflare Tunnel domain) — never a wildcard, since browsers respond to a wildcard + credentials combination by letting *any* site ride a signed-in user's or admin's session cookie. Change any time by editing `.env` and restarting the `api` service (`podman compose restart api`, or `systemctl --user restart fcculs-api` under Quadlets) — no image rebuild required. Multiple origins: `CORS_ALLOW_ORIGINS=https://a.example,https://b.example` |
| `RATE_LIMIT_SEARCH_MAX`, `RATE_LIMIT_SEARCH_WINDOW_SECONDS` | api | Per-client-IP rate limit (default 60 requests/60 seconds) applied to the unauthenticated `/api/search`, `/api/amateur` browse, and `/api/towers` browse endpoints — the app's easiest DoS/cost-abuse surface once exposed to the internet, since they run trigram/filter queries against multi-million-row tables. Change any time by editing `.env` and restarting the `api` service — no rebuild required |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_FROM_ADDRESS` | api, notifier | Outbound SMTP relay for magic-links and email/email-to-SMS alerts |
| `INGEST_CRON_HOUR`, `INGEST_CRON_MINUTE` | ingestor | UTC time of the daily ingest job |
| `MAX_DELIVERY_ATTEMPTS` | notifier | Retry cap per notification delivery |
| `DISPATCH_INTERVAL_SECONDS` | notifier-dispatch | Polling interval for matching new `change_events` to watches |

Per-watch notification channels (SMTP address, email-to-SMS carrier
gateway, or webhook URL/template — including ntfy/Discord/Telegram/Matrix
presets) are configured by end users at runtime through the web UI /
`/api/channels` endpoint, not via `.env`.

## Security Hardening

The app is designed to be exposed to the internet (e.g. via a Cloudflare
Tunnel in front of the `web` container's published port). Baseline
hardening already in place:

- **CORS lockdown** — see `CORS_ALLOW_ORIGINS` above; the API never
  reflects an arbitrary `Origin` header back with credentials enabled.
- **Webhook SSRF protection** — any user-supplied notification URL
  (webhook/ntfy/Discord/Matrix) is validated at both creation time
  (`POST /api/channels`) and send time (the `notifier` service):
  scheme is restricted to `http`/`https`, the hostname is resolved and
  rejected if it points at a loopback, private, link-local (this also
  covers the `169.254.169.254` cloud metadata address), multicast, or
  reserved IP, and redirects are never followed. Each user is also
  capped at 20 notification channels and 50 watches to limit abuse.
- **Rate limiting** — Redis-backed limits on `POST /api/auth/request-link`
  (5 requests per email+IP pair per hour) and `POST /api/admin/login`
  (5 attempts per IP per 15 minutes), so this server can't be scripted
  into a mail-spam relay against arbitrary email addresses and the
  hidden admin login can't be hammered. Requires `redis` to be reachable
  from `api` (already true in both the Compose and Quadlet deployments;
  no `.env` changes needed).
- **No default session secret** — the API refuses to start if
  `SESSION_SECRET` is left unset or at its old placeholder value, since
  this one key signs both the user and admin session cookies.
- **Correct scheme detection behind the proxy chain** — the API trusts
  `X-Forwarded-Proto`/`X-Forwarded-Host` from its container-network peers
  (`uvicorn --proxy-headers --forwarded-allow-ips=*`; safe because the
  `api` container publishes no host port and is only reachable from other
  containers on the internal network, in practice only `web`/Caddy), so
  cookies are correctly marked `Secure` when the app is actually served
  over HTTPS through Caddy + a tunnel, not just when `api` itself sees a
  raw HTTPS connection.
- **Response headers** — `web/Caddyfile` sends HSTS,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`,
  and a `frame-ancestors 'none'` CSP on every response.
- **Non-root containers** — all four app images (`api`, `ingestor`,
  `notifier`, `web`) run as an explicit non-root `USER`.

**Accepted risk**: FastAPI's interactive docs (`/docs`, `/redoc`,
`/openapi.json`) are intentionally left publicly enabled, including for
`/api/admin/*` endpoint shapes — a deliberate tradeoff for a small
self-hosted deployment, not an oversight. The hidden `/admin` panel itself
still requires the process-log-only superuser password regardless of
what `/docs` reveals about its endpoint shapes.

## Development / Testing Methodology

Every service (`ingestor`, `api`, `notifier`, `web`) has a
`tests/run_integration.sh` (or, for `web`, a container-based build/serve
smoke test) that spins up a disposable Podman pod with real Postgres/Redis,
runs unit tests, and exercises the service end-to-end against real
infrastructure — never mocks-only. Run any of them with:

```bash
bash <service>/tests/run_integration.sh
```

See `docs/plan.md` §10 (Progress Log) for what each service's test suite
covers.

## License / Attribution

FCC ULS data (Amateur Radio Service and Antenna Structure Registration
records) is public domain U.S. government data, published under the FCC's
public access program. This project performs no modification to the
underlying licensing/registration facts — it republishes and diffs the
same public records FCC itself publishes. Attribution: data sourced from
the Federal Communications Commission, Universal Licensing System (ULS),
https://www.fcc.gov/uls.

The application source code is licensed under the GNU General Public
License, version 3 — see the `LICENSE` file in this repository. You are
free to use, modify, and redistribute this software, including
commercially, provided that any distributed copies or modified versions
remain under GPLv3 and include their source code.
