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
docs/       Implementation plan and progress log
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

## Configuration Reference (`.env`)

| Variable | Used by | Purpose |
|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | postgres, migrate, api, ingestor, notifier | Database credentials |
| `SESSION_SECRET` | api | Signing key for session cookies (**required**, no default) |
| `PUBLIC_BASE_URL` | api | Base URL used to build magic-link emails |
| `PUBLISHED_PORT` | web | Host port the Caddy/web container is published on |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_FROM_ADDRESS` | api, notifier | Outbound SMTP relay for magic-links and email/email-to-SMS alerts |
| `INGEST_CRON_HOUR`, `INGEST_CRON_MINUTE` | ingestor | UTC time of the daily ingest job |
| `MAX_DELIVERY_ATTEMPTS` | notifier | Retry cap per notification delivery |
| `DISPATCH_INTERVAL_SECONDS` | notifier-dispatch | Polling interval for matching new `change_events` to watches |

Per-watch notification channels (SMTP address, email-to-SMS carrier
gateway, or webhook URL/template — including ntfy/Discord/Telegram/Matrix
presets) are configured by end users at runtime through the web UI /
`/api/channels` endpoint, not via `.env`.

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

Application source code license: TBD by the repository owner.
