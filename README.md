# FCC ULS Explorer & Alerting Service

[![Tests](https://github.com/n00tz/fcculs-explorer/actions/workflows/tests.yml/badge.svg?branch=master)](https://github.com/n00tz/fcculs-explorer/actions/workflows/tests.yml)

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

## Software Bill of Materials

The table above names the architectural choices; this is the actual
dependency manifest, kept here (rather than only in each service's
lockfile) so a reviewer or auditor doesn't have to open five different
files to see everything the app pulls in. Update this section whenever a
`requirements.txt`/`package.json`/base-image tag changes (Dependabot PRs
bump these regularly — see Development / Testing Methodology below).

**Container base images** (see each service's `Dockerfile`; version drift
is tracked automatically by `.github/dependabot.yml`'s `docker` entries):

| Image | Used by |
|---|---|
| `python:3.14-slim` | `api`, `ingestor`, `notifier` |
| `node:26-slim` (build stage only) | `web` |
| `caddy:2-alpine` (runtime stage) | `web` |
| `postgres:16-alpine` | `postgres` service (`compose.yaml`) |
| `redis:7-alpine` | `redis` service (`compose.yaml`) |

**`api/requirements.txt`** — FastAPI backend:
`fastapi==0.115.*`, `uvicorn[standard]==0.30.*`, `psycopg[binary]==3.2.*`,
`psycopg-pool==3.3.*`, `pydantic-settings==2.*`, `email-validator==2.*`,
`itsdangerous==2.*`, `aiosmtplib==3.*`, `httpx==0.28.*`, `redis==8.*`,
`rq==1.*`, `pytest==9.*`, `pytest-asyncio==1.4.*`

**`ingestor/requirements.txt`** — FCC file downloader/parser + scheduler:
`httpx>=0.28.1`, `psycopg[binary]>=3.3.5`, `apscheduler>=3.11.3`, `pytest>=9.1.1`

**`notifier/requirements.txt`** — RQ worker + delivery senders:
`psycopg[binary]==3.3.*`, `rq==2.12.*`, `redis==8.*`, `httpx==0.28.*`,
`pytest==9.*`

**`web/package.json`** — SvelteKit frontend build tooling (build-time
only; these compile the app but don't ship any code of their own into
the runtime Caddy image, which serves only the compiled static build
output):
`@sveltejs/kit ^2.5.18`, `@sveltejs/adapter-static ^3.0.2`,
`@sveltejs/vite-plugin-svelte ^7.3.0`, `svelte ^5.57.0`, `vite ^8.2.2`

**`web/package.json`** — client-side runtime dependencies (these *do*
ship, bundled into the compiled JS Caddy serves): `marked ^18.0.11`
(renders `docs/user-guide.md` as HTML on the in-app `/help` page —
see "Running with Podman Quadlets" below for how that file gets into
the image) and `marked-gfm-heading-id ^4.1.4` (gives rendered headings
real anchors so the guide's own Contents links work in-app).

No other runtime dependencies (no CDN-loaded JS, no client-side analytics/
tracking libraries, no paid third-party API SDKs) are used anywhere in the
stack, consistent with the project's "free and open source integrations
only" design goal.

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
one-off bootstrap load of the complete weekly dumps first, then
immediately catch up on every daily increment published since that
dump was cut:

```bash
podman compose run --rm ingestor python scheduler.py --bootstrap
podman compose run --rm ingestor python scheduler.py --catch-up
```

**Both steps are required.** The complete weekly dump is only cut once
a week, so on any day but publication day it is already 1–6 days stale.
The `--catch-up` run closes that gap; skipping it leaves a brand-new
instance silently missing up to a week of grants (and an empty "New
Hams" feed).

After that, the regular `ingestor` service's daily cron
(`INGEST_CRON_HOUR`/`INGEST_CRON_MINUTE` in `.env`, default 13:30 UTC)
keeps data current via the daily transaction files.

### How the daily transaction files work

This trips up every new instance, so it is worth stating plainly:

- FCC daily files are named **by weekday only** (`l_am_mon.zip`,
  `r_tow_tue.zip`, …) and are **overwritten in place every week**.
  There is no date in the filename and no archive of older days — only
  a rolling 7-day window is ever available.
- A given weekday's file contains that weekday's transactions but is
  **published around 05:00–13:00 UTC the *following* day**. So on a
  Monday, `l_am_mon.zip` still holds *last* Monday's data until the
  new one lands early Tuesday.

The scheduler therefore never guesses a filename from the current
weekday. It issues an HTTP `HEAD` against all seven files, reads each
one's `Last-Modified` header, resolves the real data date behind it,
and ingests only the days not already recorded in the `ingest_runs`
table — oldest first, so multi-day catch-ups apply in chronological
order.

To see exactly what FCC currently offers versus what has been ingested:

```bash
podman compose run --rm ingestor python scheduler.py --status
```

```
amateur:
  2026-08-31 (mon) published 2026-09-01 12:00 UTC  [ingested]
  2026-09-01 (tue) published 2026-09-02 12:00 UTC  [MISSING]
  ...
```

`--catch-up` (alias: `--run-once`) ingests everything marked
`[MISSING]`. It is **safe to re-run at any time**: the `ingest_runs`
table has a `UNIQUE (service, data_date)` constraint, so an
already-ingested day is skipped without even downloading the file, and
row-level upserts mean a forced re-ingest never duplicates data.

> **If the stack is down for more than 7 days**, the missed days have
> already been overwritten upstream and cannot be recovered from the
> daily files. Re-run `--bootstrap` (which reloads the current complete
> dump) followed by `--catch-up`.

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
  # web needs docs/user-guide.md (outside its own build dir) embedded as
  # a static asset for the in-app /help page -- pass it in as an extra
  # named build context (`deploy/update.sh` does this automatically):
  podman build -t localhost/fcculs-web:latest --build-context docs=./docs ./web
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

Once it finishes, catch up on the daily increments published since the
complete dump was cut (see
[How the daily transaction files work](#how-the-daily-transaction-files-work)
— the weekly dump is up to 6 days stale on arrival, so this step is not
optional):

```bash
podman exec ingestor python scheduler.py --status     # what's missing
podman exec ingestor python scheduler.py --catch-up   # ingest it
```

### Updating after a rebuild

For a one-off manual rebuild of a single service:

```bash
podman build -t localhost/fcculs-api:latest ./api   # rebuild what changed
# web is the one exception -- it needs the extra "docs" build context
# (see above) to pick up docs/user-guide.md for the in-app /help page:
# podman build -t localhost/fcculs-web:latest --build-context docs=./docs ./web
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

### Backups

`fcculs-backup.timer` (installed by `deploy/install-quadlets.sh` alongside
the other units, and enabled/started automatically) runs
`deploy/backup.sh` once a day: it `pg_dump`s the live database via `podman
exec` (no direct DB port exposure needed) to a timestamped,
gzip-compressed file in `BACKUP_DIR` (`.env`, default `~/fcculs-backups`),
then deletes any existing dump older than `BACKUP_RETENTION_DAYS` (`.env`,
default 3 days). This matters because `users`, `watches`, and
`notification_channels` (which can contain webhook URLs/tokens) exist only
in this database — unlike the ingested amateur/tower data, which can always
be re-downloaded from the FCC.

```bash
systemctl --user list-timers fcculs-backup.timer   # next/last run time
systemctl --user start fcculs-backup.service       # run a backup right now
journalctl --user -u fcculs-backup.service -f      # watch a run
ls -lh ~/fcculs-backups                            # list dumps
```

To restore a dump (e.g. after a disk failure, or just to verify a backup
is actually good), use `deploy/restore.sh`. It requires an explicit
`--confirm` flag since it's destructive (drops and recreates the target
database's schema before loading):

```bash
# Verify a backup without touching the live database: restore into a
# disposable side-by-side database instead.
bash deploy/restore.sh --confirm --db-name fcculs_restore_test \
  ~/fcculs-backups/fcculs-fcculs-20240101-120000.sql.gz

# Restore over the actual live database (only after downtime/data loss):
bash deploy/restore.sh --confirm ~/fcculs-backups/fcculs-fcculs-20240101-120000.sql.gz
```

Also works outside Quadlets/Compose entirely — both scripts only need
`podman` and a running `postgres`/`fcculs-postgres` container, so they
work the same way against either deployment path (Compose's `postgres`
service is named the same way, so no flags are needed there either). Not
installed by the Compose path automatically — run `deploy/backup.sh`
yourself via any scheduler (host `cron`, etc.) if you're on Compose rather
than Quadlets.

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
| `INGEST_CRON_HOUR`, `INGEST_CRON_MINUTE` | ingestor | UTC time of the daily ingest job (default 13:30, chosen to sit after FCC's ~05:00–13:00 UTC daily-file publication window) |
| `MAX_DELIVERY_ATTEMPTS` | notifier | Retry cap per notification delivery |
| `DISPATCH_INTERVAL_SECONDS` | notifier-dispatch | Polling interval for matching new `change_events` to watches |
| `BACKUP_DIR` | deploy/backup.sh, fcculs-backup.timer | Host directory daily `pg_dump` backups are written to (default `~/fcculs-backups`); override per-run with `FCCULS_BACKUP_DIR` |
| `BACKUP_RETENTION_DAYS` | deploy/backup.sh, fcculs-backup.timer | Backups older than this are deleted on every backup run (default 3 days); override per-run with `FCCULS_BACKUP_RETENTION_DAYS` |

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

**CI (`.github/workflows/tests.yml`)** runs on every push/PR against
`master` as a fast first line of defense — separate `api`/`notifier`/`web`
jobs, each installing that service's real dependencies
(`requirements.txt`/`package.json`) and running only the subset of tests
that need no real Postgres/Redis/SMTP (the mocked `unittest`-style files;
`web` runs a static `npm run build` since there's no JS unit suite yet).
It intentionally does **not** run `integration_test.py`,
`real_smtp_smoke_test.py`, or anything else needing live infrastructure —
those stay part of the manual `run_integration.sh` methodology above and
are still required before considering any change done; CI complements that
process, it doesn't replace it.

**Dependabot (`.github/dependabot.yml`)** checks weekly for updates to
each service's Python (`api`/`notifier`/`ingestor`) and npm (`web`)
dependencies, plus each service's Dockerfile base image (so a floating
tag like `python:3.12-slim`/`node:22-slim`/`postgres:16-alpine`/
`redis:7-alpine`/`caddy:2-alpine` gets flagged when a new upstream
patch/security release lands — a locally cached image won't surface
that on its own). Dependabot PRs are **not** auto-merged: review and
merge them the same way as any other change, then run
`deploy/update.sh --force` and smoke-test the result on production
before trusting a dependency/base-image bump — this is especially
important for base-image bumps, which can carry OS-level behavior
changes that a plain code review won't catch.

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
