# FCC ULS Explorer & Alerting Service — Implementation Plan

## 1. Problem Statement

Build a self-hostable, OCI-container-deployable web application that ingests FCC
public data — the **ULS Amateur Radio Service** database (`l_amat` complete +
daily/weekly transaction files) and the **Antenna Structure Registration (ASR /
"Tower")** database (complete + daily/weekly transaction files) — into a queryable
store, and exposes:

- A fast, modern web UI to browse and search Towers and Amateur Radio licenses.
- "Identity grouping" views that surface related records (same FRN/licensee,
  same tower site/coordinates, same trustee/club relationship, license history)
  so a user can discover the full picture behind a callsign, licensee, or structure.
- Free-text search by callsign or ULS System ID / File Number, with full change
  history.
- User-managed "Watches" on a callsign or ULS ID that trigger alerts (email,
  SMS via free/open channels, or generic webhook) when the daily transaction
  feed shows a change to that identity.

Target deployment: a single Podman host, **rootless containers**, driven by a
`docker-compose`/`podman-compose`-compatible stack. No proprietary/paid
integrations required for core function (email-to-SMS gateways, ntfy,
Discord/Telegram/Matrix webhooks cover "text" alerts without a paid SMS API).
No rich admin/data-editing UI in v1 — data is read-only, sourced solely from FCC files.

## 2. Confirmed Decisions (from user)

- **Hosting**: rootless Podman host; stack must run as a Compose file Podman
  can consume (`podman-compose` or `podman compose`), all containers running
  as non-root, no privileged low ports required.
- **Database**: PostgreSQL.
- **Email delivery**: self-hosted/BYO SMTP relay (no third-party API key
  dependency).
- **SMS/text approach**: pluggable notification backend — support email-to-SMS
  carrier gateways *and* generic webhooks (ntfy/Discord/Telegram/Matrix etc.),
  user chooses per-watch.
- **v1 data scope**: Amateur Radio service + ASR Tower data only. Other ULS
  services (commercial, GMRS, etc.) deferred to a later phase.
- **Backend/frontend framework**: no strong preference — proposed below,
  optimized for container simplicity on a single host and low ongoing
  maintenance.

## 3. Proposed Stack

| Concern | Choice | Rationale |
|---|---|---|
| Ingestion/API backend | **Python 3.12 + FastAPI** | Strong text/file parsing ecosystem, async I/O for downloads, easy OpenAPI docs, good Postgres tooling (SQLAlchemy 2.0 / asyncpg) |
| Database | **PostgreSQL 16** | Native trigram (`pg_trgm`) + full-text search for callsign/name search; JSONB for flexible historical diffs; mature, FOSS |
| Cache/queue | **Redis 7** + **RQ** (Redis Queue) | Lightweight FOSS job queue for notification dispatch, decoupled from ingestion cron; avoids pulling in Celery's complexity |
| Scheduler | **APScheduler** inside a dedicated `ingestor` container (or host `podman` timer/systemd unit) | Simple cron-like daily/weekly pulls, no extra service needed |
| Frontend | **SvelteKit** (static adapter) built to static assets | Small bundle, fast first paint, compiles away framework overhead — fits "modern fast interface" goal |
| Web/reverse proxy | **Caddy** | Automatic TLS, serves SvelteKit static build, reverse-proxies `/api` to FastAPI, trivially rootless-friendly (binds high ports, remapped by Podman) |
| Notifications | SMTP (`aiosmtplib`) for email + email-to-SMS gateway table; generic HTTP webhook sender; native ntfy/Discord/Telegram/Matrix adapters as webhook presets | All FOSS-compatible, no mandatory paid API |
| Auth (watch management) | Passwordless **magic-link email** sessions (no password storage, minimal surface) | Avoids building/maintaining a full auth system for a read-mostly app |
| Container base images | `python:3.12-slim`, `node:22-slim` (build stage only), `postgres:16-alpine`, `redis:7-alpine`, `caddy:2-alpine` | Small, well-maintained, rootless-compatible |

All app containers run as a non-root `USER` in their Dockerfile; Postgres/Redis
official images already support rootless/arbitrary UID operation.

## 4. Data Ingestion Design

FCC publishes, per service, a **complete weekly database dump** and **daily
transaction files**, all as ZIP archives of pipe-delimited fixed-schema `.dat`
files (layout defined in FCC's `public_access_database_definitions` spec).
This plan designs ingestion fresh against that current spec rather than
porting old code, since file formats, URLs, and hosting have had 8+ years to
drift.

- **Amateur Radio (`l_amat`)**: `HD` (header), `EN` (entity/licensee), `AM`
  (amateur-specific: class, group, trustee callsign for clubs), `HS` (license
  history), `SC`/`SF` (special conditions, free-form), `CO` (comments), `LA`
  (attachments).
- **ASR / Tower (`r_tower`)**: `EN` (owner/entity), `RA` (registration —
  coordinates, height, structure type, FAA study, construction/dismantle
  dates), `CO` (antenna coordinates array), `HS` (history), `RE`/`SC`
  (remarks) — same delimited-file convention, different schema.

> Note: the user has an old archived personal project
> (`n00tz/FCCULS-mysql`) that loaded these same two datasets into MySQL. It
> was purely a workaround for a slow FCC website ~8 years ago and is treated
> here only as informal historical context — its schema/URLs/scripts are
> **not** assumed accurate and will not be ported or relied upon; the
> `research-fcc-schema` todo below independently verifies current file
> layouts and download endpoints against FCC's live documentation.

### Ingestion pipeline (`ingestor` service)

1. **Bootstrap load**: download the latest complete dump for each service,
   parse into a Postgres staging schema, then bulk-load into the normalized
   tables via `COPY`.
2. **Daily delta job**: download the daily transaction file, parse each
   present record type, **diff against the currently stored row**, upsert,
   and write a `change_events` row per changed field. This change-event log
   is the trigger source for alerts.
3. Idempotent by design: re-running a day's file is safe (upsert by natural
   key: `unique_system_identifier` / `callsign` / `registration_number`;
   diff against current stored state, not against the previous file).
4. Parsing/schema implemented against FCC's current field-position spec,
   verified at build time, unit-tested with small fixture `.dat` snippets
   checked into the repo (not full downloads).
5. Optionally enrich records with a public zip→city/state/lat-long/timezone/
   population dataset (freely available, e.g. GeoNames) for map views and
   location-based grouping — evaluated during schema design, not assumed.

## 5. Data Model (high level)

- `entities` — FRN, name, address, entity type — the anchor for grouping.
- `amateur_licenses` — callsign, class, group code, status, grant/expiration
  dates, trustee callsign (for club stations), FK → `entities`.
- `license_history` — HS-derived audit trail per callsign.
- `towers` — ASR registration number, coordinates, height, structure type,
  status, FK → owning `entities`.
- `tower_filings` — history of tower record changes.
- `change_events` — polymorphic diff log (`subject_type`, `subject_id`,
  `field`, `old_value`, `new_value`, `effective_date`, `source_file`).
- `identity_groups` (materialized view / computed) — links `entities` sharing
  an FRN, licensees sharing a mailing address, and towers sharing
  coordinates/site — surfaced as "related records" on detail pages.
- `watches` — user_id, subject_type (`callsign`|`uls_id`), subject_value,
  notification_channel_id(s).
- `notification_channels` — type (`smtp`, `email_to_sms`, `webhook`,
  `ntfy`/`discord`/`telegram`/`matrix` preset), config JSONB.
- `users` / `magic_link_tokens` — minimal passwordless auth.

## 6. Application Features (v1)

- **Search**: callsign or ULS ID / ASR registration lookup with typeahead
  (Postgres trigram index), fallback fuzzy name search.
- **Browse**: paginated/filterable lists for Amateur licenses and Towers
  (by state, status, class, etc.).
- **Detail pages**: full attribute view per callsign/tower + timeline of
  `change_events` + "related identities" panel (grouped by FRN/address/site).
- **Watch management**: authenticated (magic-link) page to create/manage
  watches and notification channels; test-send button per channel.
- **Alert dispatch**: `notifier` worker consumes `change_events` matching
  active watches, renders a templated message, and enqueues delivery jobs
  in Redis/RQ, with retry/backoff.

## 7. Deployment Layout (Podman/Compose)

Services: `caddy`, `web` (SvelteKit static build output, served by Caddy —
no separate container needed at runtime), `api` (FastAPI), `ingestor`
(scheduled job container), `notifier` (RQ worker), `redis`, `postgres`.
All on one internal Compose network; only `caddy` publishes host ports.
Config via `.env` + Compose `secrets` for SMTP creds/DB password. Named
volumes for Postgres data and Redis persistence (if enabled). A
`compose.yaml` at repo root, verified against `podman-compose` and rootless
`podman compose` (Podman ≥ 4.x has native Compose support).

## 8. Open Items / Assumptions to Revisit During Build

- Exact FCC field-position layouts will be pulled from the current
  `public_access_database_definitions.pdf` at build time (schema is stable
  but should be verified per-service before writing parsers).
- Magic-link auth is proposed as the lightest-weight option for watch
  management; can be swapped for OAuth/passkeys later without affecting
  ingestion/data layers.
- Rate/volume of FCC daily files is modest (10s of MB); no need for
  distributed processing — single ingestor container is sufficient at this
  scale.

## 9. Todos (tracked in SQL `todos` table)

1. `research-fcc-schema` — Pull current FCC public-access database definitions
   for ULS Amateur and ASR Tower files; document exact field layouts for HD/EN/AM/HS
   and ASR equivalents, and verify current download URLs (site structure may
   have changed since any older personal projects).
2. `design-db-schema` — Finalize Postgres schema (entities, licenses, towers,
   history, change_events, identity_groups, watches, notification_channels).
3. `build-ingestor` — Implement FCC file downloader + pipe-delimited parser
   + diff-before-upsert + change-event generation, with unit test fixtures.
4. `build-api` — FastAPI service: search, browse, detail, identity-grouping,
   watch CRUD, notification-channel CRUD endpoints.
5. `build-notifier` — RQ worker + SMTP sender + webhook sender + email-to-SMS
   gateway templates + ntfy/Discord/Telegram/Matrix presets.
6. `build-frontend` — SvelteKit UI: search, browse, detail/timeline pages,
   watch management, magic-link auth flow.
7. `build-auth` — Passwordless magic-link auth (token issuance via email,
   session cookies).
8. `containerize` — Write rootless-friendly Dockerfiles for each service.
9. `compose-stack` — Author `compose.yaml`, `.env.example`, volumes/secrets,
   validate under rootless `podman compose`.
10. `docs` — README covering deployment, configuration, and FCC data licensing/attribution notes.
11. `quadlet-deployment` — Additive Podman Quadlet unit set + install/uninstall
    scripts as an alternative to the Compose stack.
12. `logout-ui` — Add a sign-out control to the frontend nav for the existing
    magic-link session (backend `/api/auth/logout` already existed, unused).
13. `admin-backend` — Hidden `/admin` panel API: log-only rotating superuser
    password, admin session cookie, paginated users/watches CRUD.
14. `admin-frontend` — Admin dashboard UI (login + Users/Watches tabs) at
    `/admin`, excluded from `robots.txt`.
15. `amateur-full-data` — Render every `amat_hd`/`amat_en`/`amat_am` column on
    the Amateur detail page with crosslinks (FRN, city/state, status, class,
    trustee/previous callsign) instead of a small attribute subset.
16. `tower-full-data` — Same treatment for Tower detail (`tower_ra`/`tower_en`)
    plus crosslinked browse-page filters read from URL query params.
17. `future-roadmap-doc` — Document explicitly deferred future features
    (other FCC ULS service databases, an MCP server) so they aren't lost.
18. `security-cors-lockdown` — Replace wildcard CORS with an explicit
    `.env`-driven origin allow-list (`FCCULS_CORS_ALLOW_ORIGINS`).
19. `security-webhook-ssrf` — Block SSRF via webhook notification channels
    (loopback/private/link-local/metadata-IP rejection, no redirects,
    per-user channel/watch caps).
20. `security-rate-limiting` — Redis-backed rate limiting on
    `POST /api/auth/request-link` and `POST /api/admin/login`.
21. `security-secret-startup-guard` — Fail API startup if
    `SESSION_SECRET` is left at its default/empty value.
22. `security-admin-cookie-scheme` — Add proxy-headers awareness so the
    admin session cookie's `Secure` flag is correct behind Caddy +
    Cloudflare Tunnel.
23. `security-response-headers` — Add HSTS/`X-Content-Type-Options`/
    `Referrer-Policy`/CSP headers to the Caddyfile.
24. `security-web-dockerfile-nonroot` — Add an explicit non-root `USER`
    to `web/Dockerfile`.
25. `security-docs-plan-update` — Document this assessment + fixes + a
    progress log entry here.
26. `watch-by-frn` — Let a user watch an FCC Registration Number (FRN)
    before any callsign/tower exists for it: `change_events.frn` column,
    synthetic `license_granted`/`tower_registered` events emitted for
    brand-new `amat_en`/`tower_en` rows during daily (non-bootstrap)
    ingest, `frn` watch subject type end-to-end (API, matcher, render),
    and a documented "new ham" callout on the watches page.
27. `guided-channel-config-ui` — Replace the freeform JSON channel-config
    textarea with per-channel-type labeled/tooltipped form controls
    (dropdowns, radio-equivalents, checkboxes) in `watches/+page.svelte`;
    no backend contract change.
28. `expand-carrier-gateways` — Add major US carriers + large MVNOs to
    `notifier/app/senders/email_to_sms.py`'s `CARRIER_GATEWAYS` table.
29. `channel-test-send` — `POST /api/channels/{id}/test`, RQ-based real
    send through the existing sender code, platform-aware verbose test
    message (respecting each platform's practical length limit), marks
    `is_verified` on success, "Send test" button in the channel list UI.
30. `notification-crosslinks` — "🔔 Watch this" links on Amateur and
    Tower detail pages (callsign, FRN, ASR registration number), visible
    only when signed in, deep-linking to the watches page with the
    subject type/value pre-filled from URL query params.
31. `browse-column-sorting` — Click-to-sort on every currently-displayed
    column in both the Amateur and Tower browse tables, backend
    allow-listed per endpoint to prevent arbitrary-column SQL injection.
32. `homepage-hero-svg` — Original themed inline SVG hero graphic
    (broadcast tower + signal arcs + connected identity-cluster nodes),
    CSS-variable-driven, reduced-motion-aware pulse animation.
33. `homepage-copy-expansion` — Expand the homepage hero copy and add a
    3-card feature grid covering browse/search, identity-grouping, and
    passwordless opt-in notifications.
34. `homepage-favicon` — Add a themed favicon derived from the same
    visual motif.
35. `field-definitions-tooltips` — Shared `web/src/lib/fieldDefs.js`
    registry (+ `CodeValue.svelte`/`CodeHint.svelte` components) mapping
    coded/abbreviated ULS fields to human descriptions, applied as
    inline-parenthetical (short) or mouseover-tooltip (long) definitions
    across the Amateur/Tower detail and browse pages, plus a new
    `/field-definitions` reference page linked from the footer. Standard
    to be followed for any future ULS dataset added to the project.
36. `new-hams-migration` — `db/006_new_operator_celebration.sql`: add
    `change_events.is_new_operator` boolean + partial index.
37. `new-hams-ingestor-flag` — `frn_has_prior_amateur_license()` helper
    in `ingestor/db.py`, threaded through `insert_change_event()` and
    `ingest.py`'s existing `NEW_RECORD_FRN_EVENT` branch for `amat_en`
    only, so a durable "first-ever license for this FRN" flag is
    computed once at ingest time and never retroactively changes.
38. `new-hams-api-endpoint` — `GET /api/new-hams`
    (`api/app/routers/new_hams.py`, rate-limited, Individual/Club
    filtering and dual totals), registered in `main.py`.
39. `new-hams-homepage-widget` — Summary line + 12-row paginated
    celebration widget on the homepage, placed below the search box,
    above the feature grid.
40. `new-hams-full-listing-page` — `web/src/routes/new-hams/+page.svelte`
    full paginated/filterable listing (25/page, type filter dropdown).
41. `new-hams-footer-link` — "New Hams" link in the footer.

Dependencies: 2 depends on 1; 3 depends on 2; 4 depends on 2,3; 5 depends on 2;
6 depends on 4,7; 8 depends on 3,4,5,6,7; 9 depends on 8; 11 depends on 9;
12,13,15,16 depend on 6; 14 depends on 13; 18-24 depend on 9 (existing
compose/Quadlet config); 25 depends on 18-24. 26 depends on 4,5 (existing
watch/notifier pipeline); 27,28 are independent of each other and of 26;
29 depends on 27 (reuses the same channel-row UI); 30 depends on 26 (needs
the `frn` subject type) and is best done after 27; 31 is fully independent.
33 depends on 32 (embeds the hero component); 34 is independent of both.
35 is fully independent of all prior items (frontend-only presentation
layer over already-ingested data). 37 depends on 36; 38 depends on 36 (but
not on 37 — the column defaults to false, so the endpoint just returns an
empty feed until the next ingest run populates flagged rows); 39,40 depend
on 38; 41 depends on 40.

## 10. Progress Log

Status as of 2026-09-05 (updated as work proceeds; see SQL `todos` table for
live status):

- ✅ `research-fcc-schema` — done. Verified real download host
  (`data.fcc.gov`, not `www.fcc.gov`) and exact field layouts against real
  downloaded sample files, catching and documenting several third-party-doc
  errors (see `docs/fcc-data-reference.md`), most notably a missing
  `content_indicator` field across all three Tower record types.
- ✅ `design-db-schema` — done. `db/001_app_tables.sql` (app-level: users,
  magic link tokens, watches, notification channels/deliveries,
  change_events), `db/002_fcc_raw_tables.sql` (corrected raw FCC tables),
  `db/003_identity_grouping_views.sql` (FRN/site/address grouping
  materialized views), `db/004_notifier_constraints.sql` (dedupe
  constraint). Validated end-to-end against real Postgres 16 with real
  fixture data.
- ✅ `build-ingestor` — done. `ingestor/` (parser, differ, downloader, db
  upsert, orchestration). Integration-tested end-to-end against a live
  Postgres container: bootstrap load + simulated daily change produced
  exactly the expected `change_events` row. Fixed a real type-mismatch bug
  in `differ.py` (DB-typed values vs. parser's raw strings) during testing.
- ✅ `build-api` — done. `api/` FastAPI service: unified trigram search,
  Amateur/Tower browse + detail (with identity-grouping panels), identity
  lookup by FRN/address. Integration-tested against real Postgres.
- ✅ `build-auth` — done (built alongside `build-api` since watch/channel
  endpoints require it). Passwordless magic-link auth: `api/app/security.py`
  (single-use hashed tokens, signed session cookies via itsdangerous),
  `api/app/mailer.py` (SMTP relay), full request-link → verify → session →
  logout flow integration-tested, including single-use enforcement and
  401-on-unauthenticated checks.
- ✅ `build-notifier` — done. `notifier/` RQ-based dispatch pipeline:
  `matcher.py` (idempotent change_event → active watch matching, backed by
  a new unique constraint), `jobs.py` (per-delivery send + status tracking),
  `senders/` (SMTP, generic webhook, email-to-SMS carrier gateways, and
  ntfy/Discord/Telegram/Matrix presets built on the webhook sender).
  Integration-tested end-to-end with real Postgres + Redis + RQ worker +
  a local HTTP capture server, including idempotency-on-rerun.
- ✅ `build-frontend` — done. `web/` SvelteKit static SPA (adapter-static,
  `ssr=false`/`prerender=false` since routes are dynamic and there's no
  Node server at runtime): search, browse, detail/identity/timeline pages
  for both Amateur and Tower data, magic-link login flow, and full
  watch/channel management UI. Built and smoke-tested in a `node:22-slim`
  container on the remote host (no local Node available either).
- ✅ `containerize` — done. Non-root Dockerfiles for `api`, `ingestor`,
  `notifier` (`python:3.12-slim`) and a multi-stage `web` build
  (`node:22-slim` → `caddy:2-alpine`, serving the static SPA and
  reverse-proxying `/api/*`). `ingestor/scheduler.py` added as the
  APScheduler-driven daily/bootstrap entrypoint. All four images built and
  smoke-tested in a disposable Podman pod (`deploy/smoke_test.sh`) with
  real Postgres/Redis; a bridge-network test confirmed Caddy resolves the
  `api` service by Compose-style DNS name and correctly proxies routes.
  Found and fixed a real bug: `COPY` preserved restrictive host directory
  permissions (700) from the build context, making the app unreadable to
  the non-root runtime user — fixed with `chmod -R a+rX` before `USER`.
- ✅ `compose-stack` — done. Root `compose.yaml` + `.env.example`: postgres,
  redis, a one-shot idempotent `migrate` job, api, ingestor,
  `notifier-worker`/`notifier-dispatch` (one image, two roles via
  different commands), and web (only port-published service). Verified on
  the remote host — no Compose provider was preinstalled, so the
  standalone `docker-compose` v2 binary was installed per-user into
  `~/.docker/cli-plugins` and `podman.socket` started; a full
  `podman compose up -d --build` brought up all 7 containers, `migrate`
  applied all 4 SQL files and exited 0, and a live end-to-end HTTP request
  (curl → Caddy → reverse-proxied `/api/search` → FastAPI → Postgres)
  returned a valid 200 JSON response. Torn down cleanly afterward.
- ✅ `docs` — done. `README.md` rewritten with deployment steps, a full
  `.env` configuration reference table, first-time bootstrap-load
  instructions, verification steps, testing methodology, and FCC data
  licensing/attribution notes.
- ✅ `quadlet-deployment` — done. `quadlet/` holds Podman Quadlet units
  mirroring every compose.yaml service: `fcculs.network`, `pgdata.volume` /
  `redisdata.volume` (names match the Compose volumes so data carries
  over), `.container` units for postgres, redis, api, ingestor,
  notifier-worker, notifier-dispatch, web, a `Type=oneshot
  RemainAfterExit=yes` `fcculs-migrate` unit (with
  `Requires=`/`After=` on dependents to reproduce Compose's
  `service_completed_successfully` gating), and a manual-start
  `fcculs-bootstrap` oneshot for the first-time full data load.
  `deploy/install-quadlets.sh` renders the templates (`.env` values
  substituted at install time, so no secrets live in the repo's units) into
  `~/.config/containers/systemd/`, reloads systemd, warns if lingering is
  off, and starts the stack in dependency order; it is idempotent.
  `deploy/uninstall-quadlets.sh` stops/removes the units while keeping the
  named volumes by default. README gained a parallel "Running with Podman
  Quadlets" section.

  **Verified on the house-voyager host (rootless Podman 4.9.3, systemd
  255)**: enabled lingering, installed the units, and brought up the full
  9-unit stack. `curl http://localhost:8080/` → 200 and
  `curl http://localhost:8080/api/search?q=W1AW` → valid JSON through
  Caddy's reverse proxy. Restarted every service unit individually with
  `systemctl --user restart` and re-verified: all 7 long-running units came
  back with no failed/inactive units and the same curl checks passed.
  Uninstall + reinstall re-verified data persistence across the cycle
  (volumes kept, stack healthy again). Real bugs found and fixed along the
  way: (1) Quadlet 4.9 supports neither `Entrypoint=` nor `NetworkAlias=`
  — the migrate job now mounts and runs `db/run_migrations.sh` (the
  postgres image's entrypoint passes non-`postgres` commands straight
  through), and containers use their Compose-matching short names
  (`postgres`, `api`, ...) as `ContainerName` so network DNS matches the
  Compose topology; (2) the SQL migrations were not actually idempotent
  despite the README claiming so — re-running them (which systemd does on
  unit restart) failed on existing tables/indexes, so every `CREATE` in
  `db/*.sql` now uses `IF NOT EXISTS` (and the `ALTER TABLE ADD
  CONSTRAINT` in 004 is wrapped in a `DO $$ ... IF NOT EXISTS` block); (3)
  `Requires=` on infra services cascaded stops on restart (restarting
  redis took down the notifiers permanently) — infra dependencies are now
  `Wants=` (only the migrate gate keeps `Requires=`), and
  `run_migrations.sh` retries transient DNS/connection failures so the
  migrate oneshot survives a postgres restart race; (4) the API briefly
  500'd right after a postgres restart on a stale pooled connection —
  psycopg_pool recovers on its own within seconds, confirmed by immediate
  successful retry.
- ✅ First real data load completed on house-voyager via
  `fcculs-bootstrap.service`: full weekly dumps ingested — amateur HD/EN/AM
  ~1.69M rows each, HS history 5.15M rows, towers RA/EN/CO ~197K/197K/203K
  rows — and `curl :8080/api/search?q=W1AW` now returns the ARRL HQ station
  with exact-match score plus trigram-similar callsigns. This surfaced a
  real performance bug: the ingestor's per-row SELECT+INSERT upsert path
  managed only ~100 rows/s over the container network (parsing alone
  benchmarks at ~103K rows/s), which would have made the bootstrap take
  multiple hours. Fixed by adding `db.upsert_rows_batch()` (psycopg
  server-side `executemany`, 2000-row batches) and using it in
  `ingest.ingest_file()` whenever `generate_diffs=False` (bootstrap /
  complete-dump loads); semantics unchanged — last-write-wins per key, no
  change_events — and daily diff-enabled ingestion keeps the original
  row-by-row diff path. HD.dat (1.69M rows) dropped from an estimated ~3
  hours to ~7 minutes; the entire two-service bootstrap now completes in
  ~30 minutes.

**Testing methodology established across all services**: since the local
Windows dev machine has no Python/container runtime, all real testing runs
on a remote rootless-Podman host over SSH, using disposable Podman pods
(Postgres 16 + Redis 7 as needed) with real schema migrations applied and
either real downloaded FCC fixture data or hand-crafted representative rows
seeded directly via SQL, exercised through the actual application code
(not just SQL) before any todo is marked done. Because the rootless Podman
host doesn't have `loginctl linger` enabled, all pod/container lifecycle
commands for a given test run are chained into a single SSH invocation.

- ✅ Post-launch fix: Amateur callsign reassignment blending, history-code
  descriptions, and browse filtering. Real operator testing against live
  data (`KJ4IKD` → `N0OTZ`) found that `amateur_detail()` queried
  `amat_hd`/`amat_en`/`amat_am` by bare `call_sign`, so a reassigned vanity
  callsign non-deterministically blended the current and prior holder's
  rows (confirmed via direct SQL probing: `N0OTZ` has two
  `unique_system_identifier` rows, one per holder). Fixed by resolving the
  current holder's USID first (`ORDER BY (license_status='A') DESC,
  grant_date DESC NULLS LAST LIMIT 1`) and scoping the "current state"
  tables to it, while `amat_hs` (license history) still queries by bare
  callsign so the full reassignment timeline stays visible; added
  `api/app/history_codes.py` with human-readable descriptions for the
  real HS log codes found in the live 5.15M-row history table; added
  partial (ILIKE) filtering on callsign/name/city/state to
  `browse_amateur()` and matching filter inputs to
  `web/src/routes/amateur/+page.svelte`. Verified live: `/api/amateur/N0OTZ`
  now returns the correct current licensee/location/class with `KJ4IKD` in
  `related_identities`, and vice versa; history rows carry
  `code_description`.
- ✅ Extended the same partial-match filtering pattern to the Tower browse
  endpoint (`browse_towers()` in `api/app/routers/towers.py`), covering
  every column shown in the Tower table: `registration_number`,
  `structure_type`, `structure_city`, and `structure_state_code` are now
  ILIKE partial matches; `overall_height_above_ground` and
  `date_constructed` got min/max and after/before range filters
  respectively (`status_code` stays an exact match, matching its
  dropdown-select UI). Confirmed `tower_ra.registration_number` is a
  primary key (one row per registration, unlike reassignable amateur
  callsigns), so the tower detail endpoint's per-table lookups do not have
  the same multi-holder blending risk the Amateur fix addressed and were
  left unchanged. Updated `web/src/routes/towers/+page.svelte` with
  matching filter inputs (registration #, structure type, city, state,
  status, height min/max, constructed after/before). Rebuilt
  `localhost/fcculs-api:latest` and `localhost/fcculs-web:latest` on
  house-voyager, restarted `fcculs-api.service`/`fcculs-web.service`, and
  verified live against the real 197K-row tower dataset:
  `/api/towers?city=atlanta` returns only Atlanta-area structures across
  multiple states, `/api/towers?heightMin=500` returns only towers ≥500 ft
  AGL, `/api/towers?constructedAfter=2020-01-01` returns only towers built
  since 2020, and `/towers` (the SvelteKit page) still returns 200 through
  Caddy.
- ⚠️ Found and fixed a deployment-process bug immediately after the tower
  filtering work: the remote host had **two divergent build directories**
  (`/tmp/build_ctx`, used for the Amateur fix, and `/tmp/fcculs-stack`, a
  separately-scp'd older checkout used for the Tower fix). Rebuilding the
  API/web images from `/tmp/fcculs-stack` silently reverted the Amateur
  filtering, the current-holder-USID resolution, and the history-code
  descriptions, because that directory's `api/app/routers/amateur.py` and
  `web/src/routes/amateur/+page.svelte` predated those fixes and it was
  missing `api/app/history_codes.py` entirely — none of that was visible
  until a user reported the regression. Root-caused via a diff of every
  `api/**/*.py` and `web/src/**` file between the two remote directories
  (only the expected tower-only differences remained afterward). Fixed by
  copying the canonical, already-correct local repo files
  (`amateur.py`, `history_codes.py`, both amateur `+page.svelte` files)
  onto `/tmp/fcculs-stack`, rebuilding both images once more, and
  re-verifying live: `/api/amateur?name=Sloan` (partial match) and
  `/api/amateur/N0OTZ` (correct current holder) both work again alongside
  `/api/towers?city=atlanta`. **Lesson for future remote work**: the
  remote host has no single canonical repo checkout — always diff the
  target build directory against the last-known-good one (or re-sync all
  changed files from the local repo, which is the actual source of truth)
  immediately before any rebuild, rather than assuming a previously-used
  `/tmp` directory already has the latest code.
- ✅ `deploy/update.sh` — done. A single-command "deploy the latest commit"
  script for the Quadlet path: `git pull --ff-only` (refuses a dirty
  working tree), rebuilds `api`/`ingestor`/`notifier`/`web`, tags each
  image both `:latest` (what the Quadlet units reference — a
  `systemctl --user restart` immediately picks it up, no unit edits
  needed) and `:<short-commit-sha>` (immutable, for rollback), stamps
  every image with an `org.opencontainers.image.revision` label carrying
  the full commit hash (so `podman image inspect` always answers "what
  commit is this?" even after `:latest`/short-sha tags get overwritten by
  a later build), then restarts `fcculs-migrate` (idempotent, safe to
  re-run) followed by every app unit. Idempotent: skips the rebuild
  entirely if HEAD didn't move and the current `:latest` image's revision
  label already matches (checked via `podman image inspect`), unless
  `--force`. Supports `--no-pull` (deploy an uncommitted local change) and
  `--no-restart` (build/tag only). Documented in a new README subsection
  under "Updating after a rebuild".

  **Verified on house-voyager** with a *fresh* `git clone` of the pushed
  GitHub repo (simulating a real "internet user" who has never touched
  the `/tmp` build directories used earlier in this session) plus the
  existing `.env` copied in: (1) first run built all 4 images, tagged
  `:latest`/`:<sha>`, applied the revision label, restarted all 6 units to
  `active`, and `curl :8080/` / `curl :8080/api/search?q=W1AW` both
  returned 200 with real data; (2) an immediate re-run correctly no-op'd
  ("Already up to date ... Nothing to do"); (3) `--force` correctly
  rebuilt anyway; (4) a plain run (git pull against an already-clean,
  up-to-date tree) succeeded end-to-end. One nit found and fixed locally:
  the script inherited the executable bit on the test clone from a manual
  `chmod +x`, which would have shown as a spurious dirty-tree diff on
  every future pull — confirmed the committed file mode matches the other
  `deploy/*.sh` scripts (644, invoked via `bash deploy/update.sh`, not
  directly).
- ✅ Decommissioned the `house-voyager` test host (`n00tz@10.64.3.38`). A
  dedicated VM/user has been provisioned for this project going forward:
  `fcculs@10.64.3.39`. Full teardown performed and verified on
  `.38`: stopped and removed all 12 Quadlet units (`bash
  deploy/uninstall-quadlets.sh --volumes --images`, after fixing CRLF line
  endings introduced by `scp`-ing from Windows — same recurring gotcha as
  prior sessions), which removed the `pgdata`/`redisdata` named volumes
  and untagged the `:latest` app images; additionally force-removed all
  leftover `:test`/`:<short-sha>` image tags and stray
  `docker.io/library/fcculs-stack-*` images left over from earlier ad-hoc
  `podman compose build` runs, ran `podman image prune -f` and `podman
  volume prune -f` to clear dangling build layers and an orphaned
  anonymous volume, deleted every leftover `/tmp/fcculs*` /
  `/tmp/build_ctx` / `/tmp/api_full` checkout directory used during this
  session's ad-hoc remote testing, reset systemd's stale failed-unit
  references (`systemctl --user reset-failed`), and disabled lingering
  (`loginctl disable-linger n00tz`) since it was enabled specifically for
  this project. Confirmed clean: `podman ps -a`, `podman volume ls`, and
  `~/.config/containers/systemd/` are all empty of anything
  fcculs-related; only generic base images (python/node/redis/postgres/
  caddy) remain cached.
- ✅ **Production now runs on the new dedicated host**: `fcculs@10.64.3.39`
  (hostname `trap-ingenuity`), a VM/user set up specifically for this
  project (not shared with other test work, unlike the retired
  house-voyager host). The operator had already cloned the repo to
  `~/fcculs-explorer`, installed the Quadlet units, and brought the stack
  up independently of this session. Verified the setup directly: all 9
  Quadlet units (`fcculs-network`, `pgdata-volume`, `redisdata-volume`,
  `fcculs-postgres`, `fcculs-redis`, `fcculs-migrate`, `fcculs-api`,
  `fcculs-ingestor`, `fcculs-notifier-worker`, `fcculs-notifier-dispatch`,
  `fcculs-web`) were `active`, lingering enabled, and the repo was a clean
  checkout one commit behind `HEAD`. Brought it fully current by running
  `bash deploy/update.sh`, which pulled the latest commit (`d91caad`),
  rebuilt all 4 application images tagged `:latest` + `:d91caad` with the
  `org.opencontainers.image.revision` label set to the full commit hash,
  and restarted `fcculs-migrate` + every app unit. Confirmed live and
  fully up to date: all 8 core units `active`, `curl :8080/` → 200,
  `/api/search?q=W1AW` → 200 with real data, and both of this session's
  filtering fixes work in production — `/api/amateur?name=Sloan` and
  `/api/towers?city=atlanta` → 200 with correctly filtered results. This
  is the first time `deploy/update.sh` has been used for a real
  production update (not just its initial test run) — worked exactly as
  designed, including hitting and immediately resolving the by-now-known
  git working-tree executable-bit nit
  (`chmod 644 deploy/update.sh` before running, same as the verification
  run on house-voyager) rather than being surprised by it.

  **Current state**: `fcculs@10.64.3.39` is the live/production host for
  this project going forward. `10.64.3.38` (house-voyager) has been fully
  decommissioned for this project (see prior entry). No further todos are
  pending; future work is operational (monitoring the daily ingestor,
  applying `deploy/update.sh` after future commits) unless new feature
  requests come in.
- ✅ `docs/user-guide.md` — done. An end-user-facing guide (as opposed to
  the operator/admin-focused README): searching, the Amateur and Tower
  browse pages' full per-field filter reference (partial-match text
  filters, exact-match status/class dropdowns, height/date range filters
  on Towers), how to read a detail page (including an explicit
  explanation of the current-holder-vs-full-history callsign-reassignment
  behavior fixed earlier this session, and the License History "Meaning"
  column), the passwordless magic-link sign-in flow, and a full walkthrough
  of My Watches (adding notification channels with the exact JSON config
  shape each channel type expects, adding watches, what triggers an
  alert) plus an FAQ. Explicitly notes that email/email-to-SMS delivery
  depends on the operator's SMTP relay being configured, and that this
  hasn't been connected/tested yet on the production instance — so
  webhook-based channels (ntfy/Discord/Telegram/Matrix/generic webhook)
  are the only ones that can be verified end-to-end for now. Linked from
  `README.md`'s Status section and Repository Layout table.
- ✅ Fixed a real SMTP-auth bug in `api/app/mailer.py`'s
  `send_magic_link_email()`, found once a real SMTP relay
  (`10.64.3.25`) was connected for the first time. The function
  unconditionally passed `username=settings.smtp_user` and
  `password=settings.smtp_password` to `aiosmtplib.send()`. Because the
  Quadlet units' `Environment=` lines always set `FCCULS_SMTP_USER` to a
  real (possibly empty) string rather than omitting it when no SMTP user
  is configured, `settings.smtp_user` ends up as `""` instead of `None` —
  and aiosmtplib treats *any* non-`None` username as "please authenticate
  after connecting," so it attempted `AUTH` against relays that don't
  support/advertise it, failing with `The SMTP AUTH extension is not
  supported by this server`. Fixed by building the `aiosmtplib.send()`
  kwargs dict conditionally — only adding `username`/`password` when
  `settings.smtp_user` is truthy — mirroring the already-correct
  `if settings.smtp_user: client.login(...)` guard in
  `notifier/app/senders/smtp.py`'s `send_smtp()` (left untouched, per the
  task). Added `api/tests/test_mailer.py` (4 mocked `unittest.TestCase`
  regression tests, matching `notifier/tests/test_senders.py`'s
  mock-the-network-boundary convention): empty-string user → no
  username/password kwargs, `None` user → same, configured user → both
  kwargs passed correctly, and configured user with `None` password →
  password defaults to `""`. Wired into `api/tests/run_integration.sh`'s
  existing `pytest tests/test_security.py ...` invocation.

  **Tested for real, not just mocked**, per this project's established
  methodology: added `api/tests/real_smtp_smoke_test.py`, a manually-run
  smoke test (same "not auto-collected by pytest, run directly with
  `python3 tests/real_smtp_smoke_test.py`" convention as
  `integration_test.py`'s real-Postgres model) that sends a real magic-link
  email against a live SMTP listener. Ran it on the production host
  (`fcculs@10.64.3.39`) against a disposable `aiosmtpd` Debugging-server
  container (a real listener that does not support/advertise `AUTH`,
  isolated on its own throwaway Podman network) in two configurations to
  prove the before/after: (1) with the **original, unfixed**
  `mailer.py` (checked out from git history into a separate temp
  directory) and `FCCULS_SMTP_USER=""`, the send failed with the exact
  reported error — `aiosmtplib.errors.SMTPException: The SMTP AUTH
  extension is not supported by this server`; (2) with the **fixed**
  `mailer.py` and the same `FCCULS_SMTP_USER=""`, the send completed with
  no error, and the listener's debug log shows the full real email
  (From/To/Subject/body with the magic-link URL) actually received.
  Also ran the 4 new mocked unit tests plus the existing
  `tests/test_security.py` together via `pytest` (the project's actual
  test runner, not `python -m unittest`, which doesn't discover
  `test_security.py`'s plain `test_*()` functions) — all 8 passed.
  Cleaned up the disposable listener container, test network, and temp
  directories afterward.

- ✅ Fixed magic-link emails always pointing at `http://localhost:8080`
  instead of the actual public hostname a user reached the app through
  (found by the user testing sign-in for real through the Cloudflare
  Tunnel in front of `fcculs@10.64.3.39`, after the SMTP fix above made
  emails actually deliver — the email arrived correctly, but its callback
  link was `http://localhost:8080/auth/callback?...`, unusable off the
  host itself). Root cause: `send_magic_link_email`'s link and the
  auth-verify cookie's `secure` flag both unconditionally used the static
  `settings.magic_link_base_url` (wired from `.env`'s `PUBLIC_BASE_URL`,
  default `http://localhost:8080`) — there was no mechanism to derive the
  actual public hostname the browser used.

  Added `auth.resolve_base_url(request)` in `api/app/routers/auth.py`:
  by default, derives the base URL from the incoming request's Host
  header (preferring `X-Forwarded-Host`) and scheme (`X-Forwarded-Proto`,
  falling back to Cloudflare Tunnel's `Cf-Visitor` header's scheme field,
  then the request's own scheme) — Caddy's `reverse_proxy` passes the
  original Host header through to the `api` service unchanged and sets
  the `X-Forwarded-*` headers, and a Cloudflare Tunnel passes them through
  unmodified in turn, so this works without any operator configuration.
  Added `FCCULS_TRUST_REQUEST_HOST` (default `true`) to opt back into the
  old static-`PUBLIC_BASE_URL`-always behavior for reverse proxies that
  don't forward these headers reliably; `PUBLIC_BASE_URL` itself remains
  as the fallback used when trust is disabled or a request somehow has no
  Host header at all. Wired the new var through `compose.yaml`, the
  `fcculs-api.container` Quadlet template, and
  `deploy/install-quadlets.sh`'s substitution list; documented in
  `.env.example` and README's configuration reference table.

  Added `api/tests/test_auth_base_url.py` (6 unit tests: plain Host
  header, `X-Forwarded-Host`/`-Proto` precedence over Host, `Cf-Visitor`
  scheme fallback, request-scheme fallback when no proto headers present,
  static-config fallback when no Host header at all, and the
  `trust_request_host=false` override), wired into `run_integration.sh`
  alongside the existing suites. Verified on `fcculs@10.64.3.39` in a
  disposable container (overlaying the changed files onto a full copy of
  the current `api/` tree so imports resolve): all 14 unit tests
  (existing `test_security.py` + `test_mailer.py` + the 6 new tests) pass,
  and the full `integration_test.py` — including the
  `auth request-link/verify/me` flow exercised through FastAPI's
  `TestClient` (whose default `Host: testserver` header round-trips
  correctly through `resolve_base_url`) — passes unchanged. Deployed via
  `deploy/update.sh` on production; not yet re-verified live through the
  actual Cloudflare Tunnel domain (the sign-in request tested during the
  SMTP fix above was made directly against `localhost:8080` on the host,
  which is why the bug wasn't caught then — a real tunnel-domain retest is
  the natural next verification step).

- ✅ `logout-ui`, `admin-backend`, `admin-frontend`, `amateur-full-data`,
  `tower-full-data`, `future-roadmap-doc` — done. Four user-requested
  features landed together:

  1. **Logout UI**: `web/src/lib/auth.js` (shared `user`/`authChecked`
     store + `refreshUser()`/`logout()`) wired into the nav bar (shows
     signed-in email + a Sign out button) and the auth callback page
     (refreshes the store immediately after `/auth/verify` so the nav
     updates without a reload). The backend `/api/auth/logout` endpoint
     already existed but had no frontend caller until now.

  2. **Hidden `/admin` panel**: `api/app/admin_auth.py` generates a
     random `secrets.token_urlsafe(18)` password once per API process
     start, keeps only its SHA-256 hash in memory, and logs the plaintext
     once via `logger.warning()` — there is no admin password setting
     anywhere (no env var, no `.env` entry, no DB row), so the *only* way
     to learn the current password is reading the API container's logs,
     per the request. A separate `itsdangerous`-signed admin session
     cookie (distinct salt from the user-session cookie, same
     `SESSION_SECRET`) gates `api/app/routers/admin.py`'s paginated
     users/watches list + edit + delete endpoints, exposed at
     `web/src/routes/admin/+page.svelte` (excluded via `robots.txt`).
     Operational quirk worth remembering: the password rotates on every
     API restart, including every `deploy/update.sh` run, so an operator
     must re-check current logs after each deploy rather than reusing an
     old password (the admin session cookie itself persists sign-in
     across that rotation as long as it isn't cleared).

  3. **Amateur/Tower full-data + crosslinking**: both detail endpoints
     already did `SELECT *` against the raw ULS tables, so this was a
     frontend-only change — the Amateur and Tower detail pages now render
     every `amat_hd`/`amat_en`/`amat_am` and `tower_ra`/`tower_en` column,
     with crosslinks from FRN → `/identity/frn/{frn}` (a new page listing
     every Amateur/Tower record sharing that FRN), and from
     status/operator class/city/state → the corresponding browse page
     with that filter pre-applied. The browse pages (`amateur/+page.svelte`,
     `towers/+page.svelte`) were updated to read `state`/`city`/`status`/
     `class`/`structureType` from the URL's query string on mount so those
     crosslinks (and clicking any filterable pill in the browse table
     itself) actually pre-populate and apply the filter, not just link to
     an empty browse page.

  4. **Future roadmap documented** (not built, per the user's explicit
     request to only note them): ingesting the other public FCC ULS
     service databases beyond Amateur/Tower (e.g. GMRS, commercial
     land-mobile, broadcast), and building an MCP server exposing this
     app's search/browse/identity-grouping data to LLM tooling. See the
     new "12. Future Features (Deferred)" section below.

  Testing: added `api/tests/test_admin_auth.py` (password-hash
  roundtrip/uniqueness across two `init_admin_password()` calls including
  parsing the actual log line the same way an operator would, admin
  session cookie roundtrip/tamper/garbage rejection) and extended
  `api/tests/integration_test.py` with a full admin-panel flow (wrong
  password rejected, login, list users, edit a user's email, delete a
  user, logout, then confirm `/api/admin/users` 401s again) through
  FastAPI's `TestClient` against a real Postgres instance, matching this
  project's established pattern. Ran the full suite
  (`api/tests/run_integration.sh`, 19 unit tests + the extended
  integration script) in a disposable `python:3.12-slim` container on
  `fcculs@10.64.3.39` — one flaky test was found and fixed along the way
  (tampering only the *last* base64 character of the admin cookie's HMAC
  signature can occasionally decode to the same bytes, since the final
  character of a base64-encoded digest can encode unused bits; changed
  the test to tamper a payload character instead) and one wrong status
  code assumption was found and fixed (`/api/admin/logout` returns 200
  like the existing `/api/auth/logout`, not 204) — all 19 unit tests +
  the full integration script passed after both fixes.

  Deployed via `deploy/update.sh` on `fcculs@10.64.3.39` (both `api` and
  `web` images rebuilt, all Quadlet units restarted and confirmed
  `active`). Live-verified: `GET /` → 200, `GET /admin` → 200 (SPA
  shell), `GET /api/search?q=W1AW` → 200, logged into `/admin` for real
  using the password read out of `journalctl --user -u fcculs-api`,
  listed/edited/deleted a real test user via the admin API, and listed
  real watches. Also re-checked the specific data bug reported earlier in
  this project (N0OTZ showing the previous callsign holder's info mixed
  with the current one) against the live API — `GET /api/amateur/N0OTZ`
  now correctly returns only the current holder's `entity`/`amateur_specific`
  data (Rial Sloan II, Ringgold GA), confirming that fix is still intact
  after this session's detail-page rewrite, and confirmed a crosslink
  query end-to-end (`GET /api/amateur?state=GA` returns GA-filtered
  results, the same query param the new detail-page state links now
  produce). Cleaned up all disposable test containers/pods and the test
  user rows created during admin-panel verification.

- ✅ `security-cors-lockdown`, `security-webhook-ssrf`,
  `security-rate-limiting`, `security-secret-startup-guard`,
  `security-admin-cookie-scheme`, `security-response-headers`,
  `security-web-dockerfile-nonroot`, `security-docs-plan-update` — done.
  Ahead of exposing the app to the internet via a manually-configured
  Cloudflare Tunnel, the user asked for an assessment focused on three
  questions: can the email feature be abused, can the hidden `/admin`
  panel be backdoored, and is there any RCE ("pop a shell") surface.

  **Assessment findings**: no SQL/command injection, unsafe
  deserialization, or path traversal anywhere — no RCE-class bug exists.
  The real risk was account/session takeover and internal-network abuse:
  (1) CORS was `allow_origins=["*"]` with `allow_credentials=True`
  (`api/app/config.py`, `api/app/main.py`), which Starlette turns into
  reflecting any `Origin` header back with credentials allowed — any
  malicious site could steal a signed-in session (including an admin's)
  via a cross-origin `fetch(..., {credentials:"include"})`; (2) webhook
  notification channels accepted any URL with no scheme/host validation
  (`api/app/routers/channels.py`, `notifier/app/senders/webhook.py`),
  an unrestricted SSRF vector from the notifier's position on the
  internal network (reachable to `postgres`/`redis`/`api`), with no
  per-user cap making it trivially repeatable; (3) `POST
  /api/auth/request-link` and `POST /api/admin/login` had no rate
  limiting, letting an anonymous visitor spam real "sign in" emails at
  any address (email-harassment-via-relay) or hammer the admin login
  with no backoff; (4) nothing guarded against `SESSION_SECRET` being
  left at its literal default (`"change-me-in-production"`), which signs
  both the user and admin session cookies — the single most damaging
  possible misconfiguration, previously silent. Medium items: the admin
  cookie's `Secure` flag was computed from the raw (non-proxy-aware)
  request scheme, so it would likely be set without `Secure` behind
  Caddy + Cloudflare Tunnel; no security response headers were sent by
  Caddy; `web/Dockerfile` had no explicit non-root `USER` (low real risk
  under rootless Podman's user namespace, but cheap to fix). Per the
  user's explicit choice after being shown the tradeoff, FastAPI's
  `/docs`/`/redoc`/`/openapi.json` were left public (accepted risk, not
  a defect) — this fully discloses endpoint shapes including
  `/api/admin/*`, but the log-only rotating admin password still gates
  actual admin use.

  > **Correction (added later, see §12b).** The accepted risk recorded
  > in the preceding paragraph **never actually existed**, and the
  > statement above is wrong. `web/Caddyfile` proxies only `/api/*` to
  > the API container, while FastAPI serves its documentation at
  > `/docs`, `/redoc` and `/openapi.json` — paths Caddy hands to the
  > SvelteKit SPA fallback instead. Those URLs therefore return the
  > web app's `index.html` **with a `200`**, not a spec, which is why
  > the mistake went unnoticed: a status-code-only check sees them as
  > healthy. `/api/docs` and `/api/openapi.json` return `404`. The
  > practical consequences are the opposite of what was recorded: no
  > endpoint shapes are disclosed, there is no live "Try it out" UI,
  > **and the API has no reachable machine-readable contract at all.**
  > Making one available is now tracked as a deferred feature in §12b.

  **Fixes**: CORS now reads an explicit allow-list from a new
  `FCCULS_CORS_ALLOW_ORIGINS` env var (comma-separated, default
  `https://fcculs-explorer.n00tz.net`), wired through `compose.yaml`,
  `quadlet/fcculs-api.container`, and `deploy/install-quadlets.sh` like
  other `.env`-driven settings, documented in `.env.example` and
  README. Webhook URLs are now validated at both creation time
  (`POST /api/channels`) and send time via a new `url_safety.py` module
  (independent copies in `api/app/` and `notifier/app/`, kept manually
  in sync) that restricts scheme to `http`/`https`, resolves the
  hostname and rejects loopback/private/link-local/multicast/reserved/
  unspecified IPs (covers the `169.254.169.254` metadata address), with
  `httpx`'s `follow_redirects` left at its default `False`; added
  per-user caps (20 channels, 50 watches). Added a Redis-backed
  fixed-window rate limiter (`api/app/ratelimit.py`, `INCR`+`EXPIRE`,
  chosen over in-memory limiting so limits survive restarts/multiple
  workers) applied to `request-link` (5/email+IP/hour) and
  `admin/login` (5/IP/15min). Added a startup guard in `main.py`'s
  `lifespan` that raises if `SESSION_SECRET` is empty or still the
  default, failing fast before serving traffic. Added uvicorn's
  proxy-headers support (`--proxy-headers --forwarded-allow-ips=*` in
  `api/Dockerfile`'s `CMD`) so `request.url.scheme` — and therefore the
  admin cookie's `Secure` flag — is correct app-wide behind the proxy
  chain. Added HSTS, `X-Content-Type-Options`, `Referrer-Policy`,
  `X-Frame-Options: DENY`, and `frame-ancestors 'none'` to
  `web/Caddyfile`. Added a non-root `USER caddy-app` to `web/Dockerfile`.

  Testing: added `api/tests/test_url_safety.py` and
  `notifier/tests/test_url_safety.py` (unit coverage of the SSRF guard,
  including a test-only bypass env var
  `FCCULS_ALLOW_PRIVATE_WEBHOOK_TARGETS_FOR_TESTING` used solely so the
  notifier's own integration test can deliver to its loopback mock
  server — never wired into `.env.example`, `compose.yaml`, or any
  Quadlet template), extended `notifier/tests/test_senders.py` with SSRF
  guard coverage, and extended both `api/tests/integration_test.py` and
  `notifier/tests/integration_test.py` with SSRF-rejection and
  per-user-cap checks. Ran the full suites in disposable containers on
  `fcculs@10.64.3.39` against real Postgres + Redis: **25 api unit tests
  + the full api integration script**, and **22 notifier unit tests +
  the full notifier integration script**, all passing. Found and fixed
  along the way: a too-narrow `except socket.gaierror` that didn't match
  mocked `OSError` in unit tests (widened to `except OSError`), and a
  stale integration-test assumption about admin-logout's status code.

  Deployed via `deploy/update.sh` on `fcculs@10.64.3.39`, plus a manual
  rerun of `deploy/install-quadlets.sh` (discovered `update.sh` alone
  does not re-render installed Quadlet unit files from the templates in
  `quadlet/`, so the new `Wants=fcculs-redis.service`,
  `FCCULS_REDIS_URL`, and `FCCULS_CORS_ALLOW_ORIGINS` lines added to
  `fcculs-api.container` required a full reinstall + `systemctl --user
  daemon-reload` to take effect) followed by restarting `fcculs-api`/
  `fcculs-web`. Live-verified against the real internet-facing stack:
  `GET /` and `GET /api/search` return 200 with all 5 new security
  headers present; a CORS preflight (`OPTIONS` with
  `Origin: https://evil.example`) gets **no**
  `Access-Control-Allow-Origin` header back, while the same preflight
  from the real allowed origin gets it correctly reflected; repeated
  `POST /api/admin/login` attempts return `401` for wrong-password
  attempts and then `429` once the configured 5-per-window limit is
  reached, confirming the limiter is live and enforcing in production,
  not just in the test suite. Cleaned up all disposable test
  containers/pods and scratch files created during verification.

- ✅ `watch-by-frn`, `guided-channel-config-ui`, `expand-carrier-gateways`,
  `channel-test-send`, `notification-crosslinks`, `browse-column-sorting` —
  all done. Added a nullable `change_events.frn` column
  (`db/005_frn_watch_support.sql`); the ingestor's daily (non-bootstrap)
  path now emits one synthetic `license_granted`/`tower_registered` event
  for any brand-new `amat_en`/`tower_en` row with a non-blank FRN, so a
  user can watch an FRN before any callsign/tower exists for it — verified
  end to end with a synthetic new-FRN row in a disposable ingestor
  container. Added `frn` as a `watches.subject_type`, wired through the
  matcher and message renderer. Replaced `watches/+page.svelte`'s freeform
  JSON channel-config textarea with per-channel-type labeled form controls
  (dropdowns/checkboxes/tooltips) and added a "new ham, don't have a
  callsign yet?" callout above the Add-a-watch form; expanded
  `email_to_sms.py`'s carrier table with 11 additional major US carriers
  and MVNOs. Added `POST /api/channels/{id}/test` (enqueues a real RQ job
  onto the same queue the notifier consumes, polls briefly, marks
  `is_verified` on success) plus a platform-aware verbose test-message
  renderer and a "Send test" button per channel. Added "🔔 Watch this"
  crosslinks on Amateur/Tower detail pages (callsign, FRN, ASR
  registration number) that deep-link to the watches page with the
  subject pre-filled from URL query params. Added click-to-sort `<th>`
  headers to both browse tables, backed by a per-endpoint column
  allow-list (`SORTABLE_COLUMNS`) to prevent arbitrary-column injection.

  Found and fixed along the way: (1) `run_integration.sh` for all three
  services only applied migrations through `003`/`004`, never the new
  `005` — fixed to apply it (api's script had also been missing `004`);
  (2) a pre-existing flaky tamper-detection test in
  `api/tests/test_security.py` (same root cause — and same fix — as a
  previously-fixed equivalent in `test_admin_auth.py`: the trailing
  base64 character of an HMAC digest can occasionally decode unchanged
  when flipped).

  Testing: extended `api/tests/integration_test.py` (FRN watch
  create/delete, sort/order acceptance + invalid-column 400 rejection on
  both browse endpoints, test-send ownership check + timeout-path check)
  and `notifier/tests/test_senders.py` (`TestRenderTestMessage` — every
  channel type, per-platform length limits, unknown-type fallback). Ran
  the full ingestor/api/notifier suites in disposable containers on
  `fcculs@10.64.3.39` against real Postgres + Redis — all passing (api:
  25 unit + full integration; notifier: 26 unit + full integration;
  ingestor: full integration incl. the FRN scenario).

  Deployed via `deploy/install-quadlets.sh` (new `FCCULS_QUEUE_NAME` env
  var) + `deploy/update.sh`, then live-verified `GET /`, `GET
  /api/search`, and both browse endpoints' sorting (valid + invalid
  column) directly against production.

  **Two more real bugs found only by live end-to-end testing with an
  authenticated session** (there being no accessible email inbox to
  drive the normal magic-link flow, verification used a throwaway
  `users` row plus a session cookie minted with the API's own
  `create_session_cookie()` and production's real `SESSION_SECRET`
  inside the running `api` container — cleaned up afterward):

  1. A real `ntfy.sh` test-send succeeded (200 OK, confirmed in
     `fcculs-notifier-worker`'s journal) but took ~11s, longer than the
     api's 8s poll window, so the client was told `"timeout"` and
     `notification_channels.is_verified` was never set despite the send
     genuinely succeeding. Fixed by moving the `is_verified = true`
     update into `notifier/app/jobs.py::send_test_message()` itself (the
     true source of truth for whether a send succeeded, regardless of
     whether the api is still polling) and bumping
     `FCCULS_TEST_SEND_POLL_TIMEOUT_SECONDS`'s default from 8.0 to 20.0
     to better match real external-relay latency. Added a notifier
     integration-test assertion covering `send_test_message()` marking
     `is_verified`. Re-verified live: a repeat `ntfy.sh` test-send now
     returns `{"status": "sent"}` within the poll window and
     `is_verified` is `true`; a `smtp` test-send against the real relay
     at `10.64.3.25` also returned `"sent"`.
  2. **The web frontend image had been silently stuck on a stale
     pre-guided-UI build** (`org.opencontainers.image.revision` pinned
     at an old commit, `9369f3b`) since the guided-channel-config UI
     landed — `vite build` had been failing outright on
     `watches/+page.svelte`'s `<input type={f.kind}
     bind:value={...}/>` (Svelte disallows a dynamic `type=` attribute
     on an element with two-way binding), so none of this round's
     frontend work (guided channel forms, FRN watch type, watch
     crosslinks, column sorting) had actually reached production despite
     `deploy/update.sh` reporting success for the other three images.
     Fixed by branching on `f.kind` with a static `type=` per branch
     (`email`/`tel`/`url`/text-fallback) instead of interpolating it.
     Rebuilt — `vite build` now succeeds — and confirmed live by
     grepping the built `/srv` assets inside the running `fcculs-web`
     container for each new feature's marker text/class (the new-ham
     FRN callout, "Watch this callsign", `sort-th`), all present, plus
     confirming the image's revision label now matches the fixed commit.

  All test artifacts (test user, test channels, test watch) were deleted
  from production afterward.

- ✅ `homepage-hero-svg`, `homepage-copy-expansion`, `homepage-favicon` —
  all done. Added `web/src/lib/HeroGraphic.svelte`, an original inline
  SVG (no external assets/licensing concerns) depicting a broadcast
  tower emitting concentric "on the air" signal arcs next to a small
  connected cluster of identity nodes with one highlighted — visually
  tying together the notification and identity-grouping pillars in one
  graphic. Colored entirely via the site's existing dark-theme CSS
  variables (`--text-dim`, `--accent`, `--bg`, `--surface-alt`), with a
  pulse animation gated behind `@media (prefers-reduced-motion:
  no-preference)`. Rewrote the homepage hero copy
  (`web/src/routes/+page.svelte`) to explicitly cover all three
  pillars — browse/search, discover related identities, and
  passwordless opt-in notifications — and added a 3-card feature grid
  below the search box spelling out magic-link sign-in, watch-by-FRN,
  and the email/SMS-gateway/webhook + send-test options, without
  changing the existing search behavior. Added `web/static/favicon.svg`
  (a simplified version of the same tower+signal motif, with hardcoded
  colors matching the theme's palette since standalone favicons render
  outside the page's CSS-variable scope) and wired it into `app.html`.

  Testing: given the prior round's live-discovered `vite build` failure
  that silently left production on a stale image, this round explicitly
  ran a disposable `podman build` of `web/Dockerfile` on
  `fcculs@10.64.3.39` **before** touching the live stack, confirmed it
  succeeded, booted a throwaway container from the test image, and
  grepped its built `/srv` assets for the new markers (`hero-graphic`,
  `no password required`, `signal-arc`) — all present — then deleted the
  disposable container/image. Only then ran `deploy/update.sh` for
  real. Live-verified against production afterward: `GET /` → 200,
  `GET /favicon.svg` → 200, and the same marker grep against the live
  `fcculs-web` container's built assets confirmed the new hero graphic
  and copy are genuinely served, with the image's
  `org.opencontainers.image.revision` label matching the deployed
  commit.

- ✅ `test-fixtures-family-callsigns` — done. Updated the unit/integration
  tests that use representative Amateur Radio test data to use the
  user's own family callsigns (KM4TYD, N0OTZ, KJ4IKD, KI4NDF, AI4ZV,
  K0NWT, N4EWT, KJ4KLO) in place of the prior fictional placeholders
  (`K0WNL`, `K3RU`, `K5ZW`, `KA6CGD`, `KA8LJJ`, `KO6PAF`, `N0NEW`), used
  once each across `ingestor/tests/fixtures/amat_{HD,EN,HS,AM}.dat`,
  `ingestor/tests/{test_parser,test_differ,integration_test}.py`,
  `api/tests/integration_test.py`, and `notifier/tests/{test_senders,
  integration_test}.py`. Test-only change — no application code or
  deployment changes involved. One scenario deliberately mirrors a real
  fact: `api/tests/integration_test.py`'s "second amateur record sharing
  the same FRN, to prove identity grouping" case now uses `N0OTZ` and
  `KJ4IKD` (the user's real current and prior callsigns, which really do
  share one FRN), with `entity_name`/`city`/`state`/`operator_class`
  updated to match the user's real public licensee record (`SLOAN, RIAL
  II`, Ringgold GA, class G); the FRN value itself was left as a new
  clearly-fictional placeholder rather than reusing either the real FRN
  or the original fixture's unrelated real stranger's FRN. All other
  reused family callsigns kept their original fixture's fictional
  name/address/FRN fields unchanged — only the callsign identifier was
  swapped — to avoid fabricating personal details for family members
  without their actual data. `ingestor/tests/integration_test.py`'s
  "brand-new ham watching their FRN before a callsign exists" scenario
  now uses `KJ4KLO` in place of the fictional `N0NEW`. Verified by
  re-running all three services' `run_integration.sh` scripts in
  disposable containers on `fcculs@10.64.3.39` after staging the updated
  test trees — all unit and integration tests pass with the renamed
  callsigns; no production deploy needed since no application code
  changed.

- ✅ `security-host-header-spoofing-fix` — done. Found and fixed a
  Host-header-spoofing gap in `api/app/routers/auth.py`'s
  `resolve_base_url()`: it previously trusted `X-Forwarded-Host`/`Host`
  unconditionally, so any client requesting the API directly (not
  through Cloudflare Tunnel/Caddy) could supply an arbitrary
  `X-Forwarded-Host` and have it echoed straight into the emailed
  magic-link URL and the session cookie's `Secure`-flag scheme decision
  — Caddy's Caddyfile has no `header_up X-Forwarded-Host` directive to
  strip/rewrite a client-supplied value first. Fix: the resolved
  `scheme://host` is now validated against `settings.cors_allow_origins`
  (the same trusted-origin allow-list already used for CORS) before
  being trusted; on a mismatch it falls back to
  `settings.magic_link_base_url` instead, exactly like the existing
  no-Host-header/`trust_request_host=False` fallback paths. Added two
  new unit tests to `api/tests/test_auth_base_url.py`
  (`test_spoofed_host_not_in_allowlist_falls_back`,
  `test_allowlisted_host_resolves_correctly`) plus updated the file's
  `setUp`/`tearDown` to manage `cors_allow_origins_raw`; all 8 tests in
  that file (6 pre-existing + 2 new) pass, along with the full
  `api/tests/run_integration.sh` suite (27 unit tests + integration),
  run in a disposable container on `fcculs@10.64.3.39`.

  Tested for real against the live stack per this project's established
  methodology: rather than touching the production `api`/`postgres`
  containers directly, spun up two throwaway containers on the same
  `fcculs` Podman network — a debug SMTP capture server
  (`aiosmtpd.handlers.Debugging`) and a disposable copy of the rebuilt
  `fcculs-api:latest` image (same env as the real Quadlet unit, SMTP
  host pointed at the capture server) — then issued real
  `POST /api/auth/request-link` calls against it with a spoofed
  `X-Forwarded-Host: evil.attacker.example` header and inspected the
  captured outbound email. Confirmed the emailed link used the
  fallback `http://localhost:8080/auth/callback?...` (not the spoofed
  host), and a follow-up call with a legitimate
  `X-Forwarded-Host: fcculs-explorer.n00tz.net` (the real allow-listed
  origin) correctly resolved to
  `https://fcculs-explorer.n00tz.net/auth/callback?...`. Deployed the
  fix to production via `deploy/update.sh` before this live test (image
  revision label `47e5f8a...`); all disposable containers and the
  test-created `users` rows (both from the pre-fix production
  self-test and the disposable-container tests) were deleted
  afterward.

- ✅ `security-read-endpoint-rate-limiting` — done. With
  `fcculs-explorer.n00tz.net` now reachable from the open internet via
  Cloudflare Tunnel, `/api/search`, `/api/amateur` (browse), and
  `/api/towers` (browse) had no rate limiting at all — unlike
  `/api/auth/request-link` and `/api/admin/login`, which already used
  the Redis-backed `enforce_rate_limit()` helper. These three endpoints
  run trigram/filter queries against multi-million-row tables with no
  authentication required, making them the app's easiest DoS/cost-abuse
  surface. Added a per-client-IP limit to all three using the existing
  `api/app/ratelimit.py::enforce_rate_limit(key, max_requests,
  window_seconds)` helper (same Redis INCR+EXPIRE fixed-window pattern
  already used by `auth.py`/`admin.py`), keyed only by client IP (no
  email component, since these are unauthenticated GETs). Each endpoint
  gets its own Redis key namespace (`search:`, `amateur-browse:`,
  `towers-browse:`) so browsing towers doesn't consume a legitimate
  user's search budget, mirroring how `request-link`/`admin-login` are
  independently keyed today — but all three share one new setting pair,
  `rate_limit_search_max` / `rate_limit_search_window_seconds`
  (defaults: 60 requests / 60 seconds), added to `api/app/config.py`.

  Unlike the pre-existing `rate_limit_magic_link_*`/
  `rate_limit_admin_login_*` settings (which turned out to be pure
  `Settings`-class code defaults with no `.env`/Compose/Quadlet wiring
  at all), the new `rate_limit_search_*` pair was wired through the
  full deployment chain end-to-end: `.env.example`
  (`RATE_LIMIT_SEARCH_MAX` / `RATE_LIMIT_SEARCH_WINDOW_SECONDS`),
  `compose.yaml`'s `api` service environment block, the
  `quadlet/fcculs-api.container` `Environment=` lines, and
  `deploy/install-quadlets.sh`'s variable-defaults + token-substitution
  logic — following the exact wiring pattern already used for
  `CORS_ALLOW_ORIGINS`. `README.md`'s configuration reference table was
  updated to document both new variables.

  Added a new dedicated test file, `api/tests/test_ratelimit.py` (no
  prior dedicated test file for `enforce_rate_limit()` existed — it was
  previously only exercised indirectly, once per endpoint, inside
  `integration_test.py`), covering: requests under the limit are
  allowed, exceeding the limit raises `HTTPException(429)`, the fixed
  window resets after it expires (not a permanent ban), and different
  keys are independent of each other — all against a **real** Redis
  instance (no mocking), following this suite's established
  no-mock-for-infra convention. One non-obvious bug surfaced and fixed
  while writing these tests: `app.ratelimit`'s Redis client is a
  lazily-created module-level singleton bound to whichever asyncio
  event loop was running when first used, but each test method here
  runs its own `asyncio.run()` (its own fresh loop) — the naive version
  crashed with "Task ... attached to a different loop" / "Event loop is
  closed" on every test after the first. Fixed by resetting
  `ratelimit._redis = None` directly (a plain attribute reset, not an
  `await close_redis()` call, since that itself needs an event loop and
  would crash trying to close a connection bound to a prior, already-
  closed loop) in `setUp()`, and by keeping each test's own Redis calls
  — including the sleep used to prove window expiry — inside a single
  `asyncio.run()` invocation via `await asyncio.sleep()` rather than a
  blocking `time.sleep()` between two separate `asyncio.run()` calls.

  Tested per this project's established methodology: ran the full
  `api/tests/run_integration.sh` suite (now 31 unit tests, up from 27,
  plus the full `integration_test.py` suite) in a disposable Podman pod
  on `fcculs@10.64.3.39` — all pass.   Deployed to production via `deploy/update.sh` (image revision label
  `cf125b48b09c36f8fb23e3db00f8e7feccea090d`), then re-ran
  `deploy/install-quadlets.sh` to regenerate the `fcculs-api.container`
  Quadlet unit with the new `Environment=FCCULS_RATE_LIMIT_SEARCH_MAX`/
  `FCCULS_RATE_LIMIT_SEARCH_WINDOW_SECONDS` lines (a plain
  `deploy/update.sh` run alone rebuilds images and restarts units but
  does not re-render Quadlet templates, so the new env vars would not
  otherwise reach the container) and restarted `fcculs-api.service` to
  pick it up. Live-verified against production's real Redis by curling
  `http://localhost:8080/api/search?q=KM4TYD` 65 times in a tight loop:
  the first 60 requests returned 200, requests 61-65 returned 429 —
  confirming the configured default (60/60s) is enforced exactly.
  Confirmed `/api/amateur` and `/api/towers` were still returning 200
  at that same moment (proving the three endpoints' rate limits are
  independent, not a shared global counter), then waited 62 seconds and
  confirmed `/api/search` returned 200 again — proving the fixed window
  resets rather than permanently banning the client.

- ✅ `postgres-backup-restore` — done. There was no backup mechanism at
  all for the fcculs Postgres volume (`pgdata.volume`) — the ingested
  FCC data (amateur/tower tables) is fully re-downloadable, but
  `users`, `watches`, and `notification_channels` (which can contain
  webhook URLs/tokens) exist only in that one database, so a disk
  failure would have lost them permanently with no recovery path.

  Added `deploy/backup.sh`: runs `podman exec <postgres-container>
  pg_dump ...` (note: the actual container name is `postgres`, per
  `quadlet/fcculs-postgres.container`'s `ContainerName=postgres` and
  `compose.yaml`'s service name — only the *systemd unit* is named
  `fcculs-postgres.service` — the script defaults to `postgres` but is
  overridable via `FCCULS_BACKUP_POSTGRES_CONTAINER` in case an
  operator renamed it), gzip-compresses the dump to a timestamped file
  in a configurable output directory (`BACKUP_DIR` in `.env`, default
  `~/fcculs-backups`; per-run override `FCCULS_BACKUP_DIR`), writes to
  a `.tmp` path and renames on success (so a killed run never leaves a
  half-written file at the final name), and prunes dumps older than a
  configurable retention period (`BACKUP_RETENTION_DAYS` in `.env`,
  **default 3 days** per explicit instruction). Added
  `deploy/restore.sh`, which restores a dump file into a running
  Postgres container; guarded behind a required `--confirm` flag since
  it drops and recreates the target database's schema before loading
  (refuses to run without it, printing what it would do instead), and
  supports `--db-name NAME` to restore into a disposable side-by-side
  database instead of the live one — the recommended way to actually
  verify a backup is restorable without ever touching production data.

  Added a Quadlet-adjacent daily timer, `quadlet/fcculs-backup.timer` +
  `quadlet/fcculs-backup.service`, that runs `deploy/backup.sh` once a
  day. Non-obvious wrinkle discovered while wiring this up: Podman's
  Quadlet generator only transforms `.container`/`.volume`/`.network`/
  `.kube`/`.pod` files placed in `~/.config/containers/systemd/` — a
  plain `.service`/`.timer` file dropped in that same directory is
  silently ignored (never becomes a real systemd unit at all, not even
  an error). Fixed by having `deploy/install-quadlets.sh` route
  `*.service`/`*.timer` templates to the normal user unit directory
  (`~/.config/systemd/user/`) instead, while still keeping the template
  files themselves in `quadlet/` for naming/discoverability consistency
  with the `*.container` files, and having `install-quadlets.sh` run
  `systemctl --user enable --now fcculs-backup.timer` so it's scheduled
  immediately on a fresh install (`uninstall-quadlets.sh` updated to
  disable/remove it from the correct directory too). Second wrinkle:
  systemd's `ExecStart=` execs `deploy/backup.sh` directly (unlike this
  repo's other `deploy/*.sh` scripts, which are always invoked via
  `bash deploy/foo.sh` and so never needed the executable bit) — but
  git does not track/preserve the executable bit, so a fresh clone's
  copy lacks it and the unit fails with `203/EXEC`. Fixed by having
  `install-quadlets.sh` `chmod +x` `backup.sh`/`restore.sh` on every
  run, so this is handled automatically rather than requiring a manual
  step documented somewhere users won't read. Documented both scripts
  and the timer in README's "Running with Podman Quadlets" section (new
  "Backups" subsection) and added `BACKUP_DIR`/`BACKUP_RETENTION_DAYS`
  to the Configuration Reference table.

  Tested for real on `fcculs@10.64.3.39` (not just unit-level): ran
  `deploy/backup.sh` directly and confirmed it produced a real,
  non-empty 227MB gzip dump. Ran `deploy/restore.sh --confirm --db-name
  fcculs_restore_test <dump>` and confirmed it restored successfully
  (schema + data, including a `REFRESH MATERIALIZED VIEW` step for the
  identity-grouping views) into a disposable side-by-side database,
  then diffed row counts against the live database for `amat_en`,
  `tower_en`, `users`, `watches`, and `change_events` — all matched
  exactly except `amat_en` (1,694,652 restored vs. 1,694,648 live),
  attributable to a few rows ingested by the always-running `ingestor`
  service in the time between the backup and the comparison query, not
  a restore defect. Dropped the disposable test database afterward.
  Separately confirmed `restore.sh` refuses to run without `--confirm`
  (dry-run output only, non-zero exit) and that `backup.sh` fails
  loudly (non-zero exit, clear error) against a deliberately wrong
  container name. Ran `deploy/install-quadlets.sh` for real, confirmed
  `fcculs-backup.timer`/`fcculs-backup.service` were correctly rendered
  into `~/.config/systemd/user/` (not the Quadlet directory), the timer
  was enabled and scheduled (`systemctl --user list-timers`), and a
  manual `systemctl --user start fcculs-backup.service` completed
  successfully end-to-end through systemd (not just via a direct `bash`
  invocation) after the executable-bit fix. Deleted the two
  test-generated dump files from `~/fcculs-backups` afterward so only
  the timer's real future daily runs will populate that directory going
  forward.

- ✅ `ci-fast-mocked-tests` — done. There was no `.github/workflows`
  directory at all — every test run to date had been manual, over SSH,
  against a real host. That's good for the integration suites (which
  deliberately need real Postgres/Redis/SMTP and are never mocked), but
  it meant a regression in the fast, fully-mocked unit tests (the
  `unittest`-style files like `test_mailer.py`, `test_security.py`,
  etc.) wouldn't be caught until the next manual pre-deploy check —
  there was no automatic signal on every push/PR at all.

  Added `.github/workflows/tests.yml`, running on `push`/`pull_request`
  against `master`, with three independent jobs:
  - **`api`**: installs `api/requirements.txt`, then runs
    `pytest -v` (the same tool `api/tests/run_integration.sh` uses,
    not `python -m unittest`) against `test_mailer.py`,
    `test_auth_base_url.py`, `test_url_safety.py`, `test_security.py`,
    and `test_admin_auth.py` — the five files in `api/tests` that need
    no real Postgres/Redis/SMTP (verified by inspection: none import
    `app.main`/`app.database`, none open a real DB/Redis connection,
    all state is either pure logic or mocked at the boundary).
    `test_admin_auth.py` wasn't explicitly named in the request but
    was added too since it meets the stated criterion (no real infra
    required) and is pure `unittest`-style logic like the others.
    `test_ratelimit.py` is explicitly **excluded** — despite also being
    "mocked unittest-style" in naming convention, it genuinely needs a
    real Redis (`enforce_rate_limit` talks to Redis directly, by
    design, per its own Progress Log entry above) and so stays manual.
  - **`notifier`**: same pattern against `notifier/requirements.txt`
    and its two no-real-infra files, `test_senders.py` and
    `test_url_safety.py` (`notifier/tests/run_integration.sh` runs
    these via `unittest discover`, but this workflow uses `pytest`
    instead per the request — pytest runs plain `unittest.TestCase`
    files natively, so the exact same test files work unmodified under
    either runner).
  - **`web`**: there is no JS/Svelte unit test suite in this repo at
    all (no test files, no `"test"` script in `package.json`), so this
    job runs `npm install && npm run build` instead — the fastest real,
    no-backend-required check available today. Chosen deliberately: an
    earlier round of this project shipped a silently-stale production
    image because an invalid Svelte dynamic-`type=` binding broke
    `vite build` without anyone noticing until a live test caught it
    (see this file's `homepage-hero-svg`/guided-channel-config-ui
    era entries) — a CI build check exactly like this one would have
    caught that regression automatically instead of requiring a manual
    live-verification pass to notice.

  Non-obvious wrinkle: every file in `api/tests`/`notifier/tests`
  hardcodes `sys.path.insert(0, "/app")`, matching the container mount
  path each service's own `run_integration.sh` uses
  (`-v /tmp/api_full:/app:Z` etc.) — rather than fork a CI-only import
  path or edit every test file, each CI job does
  `sudo ln -s "$GITHUB_WORKSPACE/<service>" /app` before running
  pytest, so the exact same test files run completely unmodified in
  both places.

  Added a `Tests` status badge to the top of `README.md`, and a new
  paragraph in the "Development / Testing Methodology" section
  explicitly stating that this workflow is a fast first line of
  defense that complements — and does not replace — the manual
  real-infrastructure `run_integration.sh` testing already required
  before any todo is considered done.

  Tested for real (not just "should work"): rather than trust the YAML
  in isolation, reproduced each job's exact commands in disposable
  Podman containers on `fcculs@10.64.3.39` against a fresh copy of the
  checked-out tree (mirroring what a GitHub Actions runner does): the
  `api` job's 5 files (27 tests) all passed in a `python:3.12-slim`
  container with `/app` bind-mounted to a fresh `api/` copy; the
  `notifier` job's 2 files (26 tests) all passed the same way; the
  `web` job's `npm install && npm run build` completed successfully
  (~15s total, including install) in a `node:22-slim` container. All
  dry-run artifacts were deleted from the production host afterward —
  this workflow only runs on GitHub's own runners going forward, never
  on the production host. Total per-job time in the dry run was well
  under the 2-minute target; real GitHub-hosted runners will add
  `actions/checkout`/`setup-python`/`setup-node` overhead but should
  still comfortably finish inside that budget, especially once the
  `cache: pip`/`cache: npm` dependency caches are warm after the first
  run.

- ✅ `dependabot-config` — done. Added `.github/dependabot.yml` with
  eight entries, all on a weekly schedule: `pip` for `/api`,
  `/notifier`, and `/ingestor` (each has its own `requirements.txt`,
  and Dependabot's `pip` ecosystem doesn't recurse into
  subdirectories, so each needs its own `directory:` entry); `npm` for
  `/web`; and `docker` for `/api`, `/notifier`, `/ingestor`, and
  `/web` (one entry per Dockerfile-containing directory) so floating
  base-image tags (`python:3.12-slim`, `node:22-slim`,
  `postgres:16-alpine`, `redis:7-alpine`, `caddy:2-alpine`) get
  flagged when a new upstream patch/security release lands — a
  locally cached build won't pick that up on its own since the tag
  itself doesn't change, only its underlying digest.

  Documented in README.md's Development / Testing Methodology section
  that Dependabot PRs are **not** to be auto-merged: they go through
  the same review/merge path as any other change, then require a real
  `deploy/update.sh --force` run plus a smoke test on production
  before being trusted — base-image bumps in particular can carry
  OS-level behavior changes a code review alone wouldn't catch.

  This is a config-only change (no code path exercised), so there is
  no "real infra" test to run beyond confirming the YAML is
  well-formed and matches Dependabot's schema; verification will
  happen naturally the first time Dependabot opens a PR against this
  repo (expected within the first weekly cycle after this lands).

- ✅ `field-definitions-tooltips` — done. Added a shared
  `web/src/lib/fieldDefs.js` registry (`FIELD_HELP` field-level help
  text + `CODE_MAPS` code→description tables) plus two components,
  `CodeValue.svelte` (renders a coded value with its definition
  attached — inline `code (Description)` for short/single-word
  descriptions, a mouseover `.hint` tooltip for longer ones, following
  the existing tooltip pattern already used on the Watches page) and
  `CodeHint.svelte` (definition-only, for use alongside a value
  already rendered elsewhere, e.g. inside a link). Unmapped codes
  always fall back to the raw value, matching the existing
  `api/app/history_codes.py` precedent.

  Wired into: the Amateur detail page (License Status, Radio Service
  Code, Entity Type, Applicant Type, Licensee Status, Operator Class,
  Group Code, Region Code, Trustee Indicator, Vanity Relationship,
  Systematic/Vanity Callsign Change); the Tower detail page (Structure
  Type, Status, Application Purpose, Previous Purpose, Painting/
  Lighting, Proposed Marking/Lighting, NEPA Flag, and the owners/
  contacts table's Entity Type column); and both browse pages'
  sortable column headers + status/class/structure-type pills (via a
  `title=` tooltip, kept compact to avoid breaking table/mobile
  layout). Added a new `/field-definitions` reference page (linked
  from the footer) that renders the full registry as a browsable
  table, grouped by Amateur/Tower.

  Sourcing/verification: cross-checked real distinct production values
  (via direct `psql` queries against the live database) against two
  independently-maintained third-party ULS references —
  `github.com/tgies/uls` (mirrors an actual FCC-published code
  definitions file, not reverse-engineered, covering License Status,
  Application Purpose, Entity Type, Applicant Type, Operator Class,
  and generic Structure Type) and `github.com/lf-connectivity/
  ISPToolbox` (an independent ASR ingestion script citing the FCC's
  own `pubacc_asr_codes_data_elem.pdf`, used to correct an earlier
  best-effort ASR `status_code` guess — `I` is Dismantled, not
  "Inactive"; `A` is Cancelled, not "Application filed"; the towers
  browse page's status filter dropdown had the same wrong label and
  was corrected too). Documented both sources in
  `docs/fcc-data-reference.md` §7 as go-to references for decoding any
  future ULS dataset's coded fields.

  Explicitly avoided guessing: `amat_am.vanity_callsign_change` was
  initially assumed to be a simple Y/N flag, but production data shows
  6 distinct values (A/B/C/D/E/F) with no located FCC decode table
  anywhere (neither the FCC's own codes file nor either third-party
  source enumerates it) — corrected to show the raw code with a field
  help note stating the FCC does not publish a decode for it, rather
  than presenting a fabricated mapping as fact. Same treatment applied
  to `systematic_callsign_change`. A handful of ASR-specific
  `application_purpose` values observed in production (`OC`, `DI`,
  `SU`) are similarly left undecoded since they don't appear in the
  FCC's generic ULS purpose-code list.

  Tested: `npm run build` (via a disposable `node:22-slim` Podman
  container on `fcculs@10.64.3.39`, matching `web/Dockerfile`'s build
  stage) succeeded cleanly with the new `fieldDefs.js`/`CodeValue`/
  `CodeHint`/`field-definitions` route included, confirming no Svelte
  binding/import errors before this lands on production.

- ✅ `readme-sbom` — done. Added a "Software Bill of Materials" section
  to README.md, directly under the existing high-level Stack table,
  since that table only names architectural choices (e.g. "Python
  3.12 + FastAPI") without listing the actual dependency manifest.
  Lists every container base image (with which service(s) use it),
  and every package from `api/requirements.txt`,
  `ingestor/requirements.txt`, `notifier/requirements.txt`, and
  `web/package.json` verbatim, plus a note that `web`'s dependencies
  are build-time only (the runtime image is Caddy serving a static
  build) and that no other runtime dependencies (CDN JS, analytics,
  paid API SDKs) exist anywhere in the stack. Instructed readers to
  keep it in sync when Dependabot bumps a manifest/base-image tag.
  Documentation-only change; no code path exercised, so no test beyond
  proofreading the dependency lists against the actual manifest files.

- ✅ `dependabot-pr-review` — done. Worked through all 21 open
  Dependabot PRs (opened by the `.github/dependabot.yml` config added
  in the prior round). No PR-merge tool was available (the GitHub
  integration in this environment is read-only for pull requests, and
  neither the local machine nor `fcculs@10.64.3.39` had the `gh` CLI
  installed) — resolved by applying each PR's exact version bump
  directly to `master` via `git`/manual edits (verified byte-for-byte
  against each PR's diff first), which is functionally equivalent to a
  merge; GitHub/Dependabot auto-detected the satisfied versions and
  auto-closed all 21 PRs within minutes of each push, with no manual
  intervention needed. Grouped into five risk-tiered batches, each
  independently tested on `fcculs@10.64.3.39` before merging:
  - **Batch A** (PRs #18, #19, #15, #11, #17, #4, #12 — httpx 0.28,
    psycopg/psycopg-pool 3.3, apscheduler 3.11.3): single-line
    `requirements.txt` diffs, verified via each service's mocked test
    suite in a disposable `python:3.12-slim` container (api 27
    passed, notifier 26 passed, ingestor 16 passed).
  - **Batch B** (PRs #21, #6, #10, #16 — pytest 8→9, pytest-asyncio
    0.24→1.4): same mocked-test verification; confirmed no code in
    this project uses `pytest-asyncio` markers at all (async tests
    use plain `unittest` + `asyncio.run()`), so the major bump has no
    behavioral surface here.
  - **Batch C** (PRs #8, #14, #9 — redis-py 5→8, RQ 1.16→2.12,
    notifier only): higher risk since RQ 2.x is API-breaking and the
    notifier's dispatch/worker code depends on it directly — tested
    with **real Postgres + Redis**, not just mocks: ran a real RQ 2.12
    `Worker` end-to-end through `notifier/tests/integration_test.py`
    (consumed a queued `send_delivery` job, delivered a real webhook,
    marked the DB row sent) and `api/tests/integration_test.py`'s full
    31-check suite (including real-Redis rate limiting) against the
    bumped `redis` package.
  - **Batch D** (PRs #1, #2, #3 — Python 3.12-slim → 3.14-slim base
    images): required full `podman build` of all three Dockerfiles,
    not just a pip install in an existing container, since the `FROM`
    line changes. All three built cleanly (`psycopg[binary]` has cp314
    wheels available), and each service's mocked tests passed running
    inside its actual built 3.14 image.
  - **Batch E** (PRs #13, #20, #5, #7 — Svelte 4→5, Vite 5→8,
    `@sveltejs/vite-plugin-svelte` 3→7, Node 22→26 base image):
    flagged highest-risk going in (Svelte 5 is a breaking rewrite) but
    verified clean: both a bare `npm run build` and a full
    `podman build` of `web/Dockerfile` with `node:26-slim` succeeded
    with no errors (one harmless `a11y_autofocus` lint hint) — the
    existing Svelte 4 legacy syntax (`$:` reactive statements,
    `on:click`/`on:input`, `{#each}`/`{#if}`) runs unchanged under
    Svelte 5's backward-compatibility mode. Ran the built image and
    confirmed `/`, `/amateur`, `/watches`, `/towers`, and
    `/field-definitions` all returned HTTP 200 with expected markup
    before merging.

  After all five batches landed on `master` (commits `394dca6` through
  `10af842`), ran a real `deploy/update.sh --force` on
  `fcculs@10.64.3.39` — all 6 services (`postgres`, `redis`, `api`,
  `ingestor`, `fcculs-notifier-worker`, `fcculs-notifier-dispatch`,
  `fcculs-web`) restarted active/healthy. Live-verified post-deploy:
  `GET /` and `GET /amateur` on the public hostname returned HTTP 200,
  `GET /api/search?q=N0OTZ` returned real matching records, `api`'s
  container confirmed running `python3.14`, and the notifier worker
  container confirmed `redis==8.1.0`/`rq==2.12.0` installed. Cleaned up
  all disposable test containers/images/pods used during batch
  verification afterward.

- ✅ **"New Hams" celebration (homepage widget + `/new-hams` full
  listing)** — done. Adds `db/006_new_operator_celebration.sql`:
  `change_events.is_new_operator BOOLEAN NOT NULL DEFAULT FALSE` +
  a partial index (`WHERE is_new_operator`) for fast homepage/listing
  queries. `ingestor/db.py` gained
  `frn_has_prior_amateur_license(conn, frn)`, called from
  `ingestor/ingest.py`'s existing `NEW_RECORD_FRN_EVENT` branch (the
  synthetic `license_granted` event already emitted for a brand-new
  `amat_en` row) — checked **before** that row's own `upsert_row()`
  call (ordering already guaranteed this excludes the row from its own
  existence check), and set only for `table == "amat_en"` (towers never
  get the flag; the concept doesn't apply there). This makes the flag
  durable: once true, it never flips even if that FRN later gains a
  second/vanity callsign — proven directly in
  `ingestor/tests/integration_test.py`'s new checks (a genuinely new
  FRN's first grant flags `is_new_operator=true`; a second callsign
  granted to that same FRN in a subsequent daily file flags
  `is_new_operator=false`).

  New `GET /api/new-hams` endpoint
  (`api/app/routers/new_hams.py`, registered in `main.py`) — same
  per-IP rate-limit tier as `/api/search`/`/api/amateur`/`/api/towers`
  (`rate_limit_search_max`/`window_seconds`, no new setting needed).
  Joins `change_events` (`is_new_operator = true`) to `amat_en`/
  `amat_hd`, restricted to `applicant_type_code IN ('I','B')`
  (Individual/Club — other applicant types excluded from this
  celebratory feature), with an optional `type=individual|club` filter
  validated against an allow-list (never interpolated raw, same
  SQL-injection-safety pattern used for `sort`/`order` elsewhere).
  Returns both a combined `total` and split `total_individuals`/
  `total_clubs` so the summary line can show both counts per the
  user's "differentiate, don't hide" requirement. Reused `entity_name`
  directly for the display name (spot-checked real production data
  first — `entity_name` is already populated in "LAST, FIRST MI"/club
  name form for both applicant types, matching every other page in
  this project that already displays it raw, so no first/last-name
  reassembly logic was needed).

  Frontend: homepage (`+page.svelte`) gained a celebration widget below
  the search box, above the feature grid — a summary line with both
  counts, a 12-row paginated table (Callsign, Name + type pill, City/
  State, Grant Date), and a link to the new full listing. New
  `web/src/routes/new-hams/+page.svelte` mirrors the existing browse
  pages' layout/pagination conventions at 25/page with an All/
  Individual/Club filter dropdown. Footer (`+layout.svelte`) gained a
  "New Hams" link. New `.pill.type-individual`/`.pill.type-club` CSS
  variants added to `app.css`; no other new primitives needed.

  Tested per this project's established methodology: extended
  `ingestor/tests/integration_test.py` and `api/tests/
  integration_test.py` (seeded one new-individual, one new-club, and
  one "second callsign for an already-known FRN" row that must be
  excluded; asserted counts, filtering, and pagination), both run for
  real against disposable Postgres(+Redis) pods on
  `fcculs@10.64.3.39` — all checks passed, including the pre-existing
  31 API checks (nothing regressed). Ran a full `podman build` of
  `web/Dockerfile` in a disposable image to confirm the new homepage
  section and `/new-hams` route compiled cleanly (the same regression
  class — a bad Svelte binding silently breaking the build — bit this
  project once before) before ever touching production. Deployed via
  `deploy/update.sh --force`; confirmed the `is_new_operator` column
  exists in the live schema, `GET /api/new-hams` and `GET /new-hams`
  both return HTTP 200 (correctly empty until the next daily ingest —
  bootstrap loads never generate `change_events`, matching the
  existing FRN-watch feature's behavior), and the built `web` image's
  JS bundles contain the new "New Hams" UI text. Cleaned up all
  disposable pods/images used during verification afterward.

- ✅ **User guide refresh + in-app Help page** — done. `docs/user-guide.md`
  had gone stale since its original publish — it predated guided
  (no-JSON) channel setup, the expanded email-to-SMS carrier list,
  watch-by-FRN, channel test-send, "🔔 Watch this" detail-page
  crosslinks, click-to-sort browse tables, field-definition tooltips +
  the `/field-definitions` reference page, the expanded homepage copy,
  and the "🎉 New Hams" celebration. Rewrote it end-to-end, written at
  a level understandable to young/new readers, and added five new
  sections (The home page, 🎉 New Hams, Sorting any table by column,
  What do all these codes and abbreviations mean?, plus a restructured
  My Watches with FRN/guided-setup/test-send/crosslink subsections)
  and an expanded FAQ.

  Then added an in-app **Help page** (`/help`, linked from the footer)
  so this same guide is readable from inside the running app, not just
  the repo. Rather than hand-duplicating the content into a second,
  driftable copy inside `web/`, `web/Dockerfile`'s build stage now
  copies `docs/user-guide.md` in directly as a static asset (served at
  `/user-guide.md`) via a new Podman/Buildah **additional build
  context** named `docs` — since `web`'s own build context is just the
  `web/` directory and can't otherwise see `../docs`. `compose.yaml`
  (`build.additional_contexts`) and `deploy/update.sh`'s `build_image`
  helper (now accepts extra `--build-context` args, used only for the
  `web` build) both wire this through, so both the Compose and
  Quadlet/`update.sh` deploy paths stay in sync. `docs/user-guide.md`
  is therefore the single source of truth for both the repo and the
  in-app guide — no manual copy-paste to keep updated.

  `web/src/routes/help/+page.svelte` fetches `/user-guide.md` at
  runtime (client-rendered, matching this app's SPA architecture) and
  renders it with the `marked` library (MIT-licensed, matching the
  project's free/open-source-only integrations rule) plus the
  `marked-gfm-heading-id` extension so the guide's own internal
  "Contents" `#anchor` links keep working once rendered in-app. New
  `.markdown-body` typography rules added to `app.css`, themed
  entirely off the existing dark-mode CSS variables (headings, tables,
  code blocks, blockquotes) — no new hardcoded colors. Footer link
  "Help" added in `+layout.svelte`, next to Field Definitions/New Hams.

  Tested per this project's established methodology: a disposable
  `podman build --build-context docs=...` of `web/Dockerfile` on
  `fcculs@10.64.3.39` (first on a throwaway clone of a WIP branch,
  before merging to master) succeeded, and a throwaway container
  booted from it confirmed `GET /user-guide.md` served the full
  24,616-byte guide, `GET /help` returned 200, and the built JS bundle
  contained both the `marked` library and the footer's `/help` link —
  all before the WIP branch was merged to master, pushed, or deployed.
  Deployed for real via `deploy/update.sh --force` (a first run
  surfaced a real pre-existing gap in `update.sh`'s staleness-skip
  check — it only inspects the `api` image's revision label as a
  proxy for "already built this commit," so a genuinely failed `web`
  build on an earlier interactive attempt was masked on the next
  invocation; noted here for future awareness, not fixed as
  out-of-scope for this task). Live-verified against production
  afterward: `GET /`, `GET /help`, and `GET /user-guide.md` all return
  200, the served guide is the full 24,616 bytes, and the running
  `fcculs-web` container's `org.opencontainers.image.revision` label
  matches the deployed commit.

- ✅ **`update.sh` skip-check bugfix: inspected only `api`'s revision
  label, not all four images** — done. `deploy/update.sh`'s
  "already up to date, nothing to do" fast-path only inspected the
  `org.opencontainers.image.revision` label on `$API_IMAGE` as a proxy
  for "did we already build this commit," even though the script
  builds `api`, `ingestor`, `notifier`, and `web` sequentially. Since a
  later image's build can fail after an earlier one already succeeded
  (this project hit exactly this during the Help-page work above — an
  interactive `web` build attempt failed on the `COPY --from=docs`
  step before the `docs=` build-context wiring was correct), a retry
  with no new commits pulled could see `api`'s label already matching
  the current commit and report "Already up to date... Nothing to
  do," silently leaving a genuinely stale/never-successfully-built
  `web` (or `ingestor`/`notifier`) image in place indefinitely — the
  live-service equivalent of a silent no-op deploy.

  Fix: the skip check now loops over all four image refs
  (`API_IMAGE`, `INGESTOR_IMAGE`, `NOTIFIER_IMAGE`, `WEB_IMAGE`) and
  only skips the rebuild if **every one** already carries the current
  commit's revision label; if any single image's label doesn't match,
  the full rebuild proceeds as normal. Updated the script's header
  comment to describe the corrected behavior.

  Tested for real on `fcculs@10.64.3.39` per this project's
  methodology (on a disposable clone at `/tmp/update-sh-test`, using
  a throwaway `.env` pointing `API_IMAGE`/`INGESTOR_IMAGE`/
  `NOTIFIER_IMAGE`/`WEB_IMAGE` at `updatesh-test-*` image names so
  real production images were never touched): built a baseline where
  all four images carried the current commit's label and confirmed a
  re-run correctly printed "Already up to date... Nothing to do";
  then intentionally re-tagged just the `web` image's `:latest` with
  a fake stale revision label (`deadbeef...`) while leaving
  api/ingestor/notifier's labels matching the current commit, and
  confirmed a re-run **did not** skip — it rebuilt all four images and
  correctly re-labeled `web` with the current commit's real revision.
  Cleaned up all disposable test images/clone afterward. Merged to
  `master` and deployed via `deploy/update.sh --force` on production
  afterward with no incident.

### Daily ingestor catch-up redesign + 10-day New Hams window

- **Symptom reported by the user**: the daily job run on 2026-09-07
  imported *week-old* data, and the Amateur Radio Licenses table's most
  recent grants were stuck at 2026-08-31 despite several days of
  apparently-successful daily runs.
- **Root cause (confirmed against live FCC `Last-Modified` headers)**:
  FCC daily transaction files are named **by weekday only**
  (`l_am_mon.zip`, `r_tow_tue.zip`, …) and are **overwritten in place
  on a 7-day rotation** — there is no date in the filename and no
  upstream archive. Critically, a given weekday's file is published
  **~05:00–13:00 UTC the *following* day**. The old scheduler did
  `DAYS_OF_WEEK[run_date.weekday()]` at 07:00 UTC, i.e. it fetched
  "today's" filename *before* today's file had been published — which
  still contained the **same weekday from the previous week**. Verified
  empirically: on Mon 2026-09-07, `l_am_mon.zip` carried
  `Last-Modified: Tue, 01 Sep 2026 12:00:09 GMT` → 2026-08-31 data.
  This also meant every day published *between* runs was silently
  skipped forever, producing the reported gaps.
- **Redesign** (`ingestor/scheduler.py`, `downloader.py`, `db.py`):
  the scheduler no longer guesses a filename from the calendar. It
  `HEAD`s all seven weekday files, reads each `Last-Modified`, and
  resolves the real data date by walking backward to the first matching
  weekday (robust to late/holiday publication, unlike a naive
  "publish date − 1 day"). It then ingests only the days not already
  present in a new `ingest_runs` table, **oldest first**, each in its
  own temp dir so a mid-catch-up failure still keeps earlier days
  recorded. `effective_date` is now stamped with the file's **real data
  date** rather than the run date — the actual source of the
  wrong-dated change events.
- **Dedupe** (`db/007_ingest_run_tracking.sql`): new `ingest_runs`
  table keyed `UNIQUE (service, data_date)`, recording source file,
  `Last-Modified`, a content SHA-256, row/change counts, and status.
  An already-ingested day is skipped **without downloading**; row-level
  upserts mean even a forced re-ingest cannot duplicate data.
- **Cron moved 07:00 → 13:30 UTC** (`.env.example`, `compose.yaml`,
  `install-quadlets.sh`, scheduler defaults) to sit after FCC's
  publication window. Note the redesign makes this a latency
  optimization, not a correctness requirement — catch-up is
  self-healing regardless of run time.
- **New CLI**: `--status` (prints FCC-available vs. ingested days with
  `[ingested]`/`[MISSING]` marks), `--catch-up` (alias `--run-once`),
  `--max-days`.
- **New Hams**: window widened to 10 days (`NEW_HAMS_WINDOW_DAYS`) so
  ingestion gaps are visible at a glance rather than hidden. Sort is
  `grant_date DESC, call_sign ASC` — deliberately on **grant date**,
  the column the UI actually displays, since sorting on the invisible
  `effective_date` made the table look unsorted (verified against real
  data: grant_date tracks effective_date for 324 of 326 rows).
  `db/007` adds a matching partial index; the `db/006` index no longer
  matched the new sort.
- **Verification on production (`fcculs@10.64.3.39`)**, per this
  project's methodology:
  - 14 new scheduler unit tests (real observed FCC headers as fixtures,
    late-publication, catch-up skip/ordering, effective-date
    correctness, non-fatal missing archive members) — all pass; full
    mocked ingestor suite 28/28 in a disposable `python:3.14-slim`
    container.
  - `--status` against the live DB correctly listed all 14
    service/day combos as `[MISSING]`.
  - Deleted the 2,915 mis-stamped `change_events` from the three buggy
    runs (0 `notification_deliveries` referenced them; bootstrap
    generates none, so all existing rows were from the bug), then ran
    a real `--catch-up`: **all 7 days × 2 services ingested**
    (2026-08-31 → 2026-09-06), 18,068 amateur + 1,373 tower rows,
    8,964 + 6,518 change events. `amat_hd` max `grant_date` advanced
    2026-08-31 → **2026-09-05**, and `change_events` now spread
    correctly across real dates with 326 new operators (322
    individuals, 4 clubs).
  - **Dedupe proven for real**: an immediate second `--catch-up`
    reported `nothing to do -- all 7 available day(s) already
    ingested` for both services, downloaded nothing, and skipped the
    materialized-view refresh.
  - Empty weekend archives (FCC publishes a ~212-byte stub zip with no
    `.dat` members when there's no business day) are handled
    non-fatally **and still recorded**, so they aren't retried forever.
  - Live `GET /api/new-hams` returned `window_days: 10`, `total: 326`,
    `total_individuals: 322`, `total_clubs: 4`, correctly ordered.
- **Documentation**: README gained a "How the daily transaction files
  work" section (weekday rotation, D+1 publication, `--status`/
  `--catch-up`, and an explicit warning that a >7-day outage requires a
  fresh `--bootstrap` since the missed days are gone upstream), and the
  first-time-load instructions in both the Compose and Quadlet paths
  now state that `--bootstrap` **must** be followed by `--catch-up`
  (the weekly dump is up to 6 days stale on arrival — the single most
  likely way a new instance silently starts with a data gap).
  `docs/user-guide.md` updated for the 10-day window and sort order.

### Architecture diagrams (`docs/architecture.md`)

- **Motivation**: the repo had thorough prose documentation (README for
  deployment/config, user-guide for end users, this plan for history) but
  nothing that showed the *shape* of the system — how data moves, and
  what decisions each component makes. Several behaviours that took real
  investigation to get right (the FCC weekday-rotation catch-up, the
  synthetic-event/`is_new_operator` branch, the dispatch/worker split,
  the all-four-images revision check) were documented only as paragraphs
  of explanation or as commit archaeology.
- **Format: Mermaid in Markdown**, deliberately. GitHub renders it
  natively, so there is no build step, no image toolchain, and no
  generated `.svg`/`.png` assets that can silently drift out of sync with
  the source — the diagram *is* the source, editable in a normal diff.
- **14 diagrams across 12 sections**: container topology; level-0 data
  flow; the daily catch-up flowchart; the per-row ingest decision tree;
  the notification pipeline (sequence); delivery state machine; the
  magic-link auth sequence; test-send; the read-request lifecycle;
  an ERD of the data model; the `update.sh` decision flow; and
  operational runbooks for fresh install, gap diagnosis, and
  backup/restore.
- **Content is derived from the code, not from memory** — each diagram
  was written after re-reading the relevant module (`dispatch.py`,
  `matcher.py`, `jobs.py`, `ingest.py`, `scheduler.py`, `auth.py`,
  `main.py`, `Caddyfile`, the `db/*.sql` migrations), so the branches
  shown match what actually executes. Several diagrams pair with a short
  "why" note capturing the non-obvious rationale (double idempotency
  guard in matching, why `is_new_operator` is stored rather than derived,
  why the worker rather than the api owns the `is_verified` write, why
  the host-header allow-list check exists).
- **Verification** (Mermaid fails *silently* on GitHub — a broken diagram
  renders as nothing, so this needed real checking, not eyeballing):
  - First pass with `mermaid.parse()` under jsdom in a disposable
    `node:22-slim` container. Initially reported "ALL DIAGRAMS VALID"
    while having found **0 blocks** — the extraction regex didn't match
    CRLF line endings. Caught by asserting the block count, not just the
    pass/fail; fixed and confirmed 14/14 parse.
  - Parse-only proved insufficient: jsdom can't render (no
    `CSSStyleSheet`), and parsing wouldn't catch HTML-in-label issues.
    Ran a full browser render via the `minlag/mermaid-cli` container —
    **14/14 rendered**, all SVGs non-empty.
  - That render surfaced a real defect: `<b>` emphasis renders as
    *literal* `&lt;b&gt;` text inside `sequenceDiagram` messages (which
    escape HTML), unlike flowchart labels where it renders correctly.
    One occurrence in the auth diagram; rewritten without markup and
    re-rendered to confirm 0 literal tags remain.
- **Cross-referenced, not inlined**: linked from README's Repository
  Layout as its own short section, plus targeted pointers from the three
  places a reader is most likely to want a picture — the daily-file
  explanation (§3 + §12), `update.sh` (§11), and gap diagnosis.

### Progress Log — Dependabot api dependency batch (#22–#26)

Worked through five open Dependabot PRs, all single-line bumps to
`api/requirements.txt`. Because every PR touched adjacent lines of the
same file, they could not be merged independently without conflicts, so
all five were applied together on a `deps/dependabot-batch` branch off
current master and validated as one unit.

**Scope of the bumps**

| Package | From | To | PR |
|---|---|---|---|
| `fastapi` | `0.115.*` | `0.141.*` | #23 |
| `uvicorn[standard]` | `0.30.*` | `0.52.*` | #25 |
| `psycopg[binary]` | `3.2.*` | `3.3.*` | #22 |
| `aiosmtplib` | `3.*` | `5.*` | #26 |
| `rq` | `1.*` | `2.*` | #24 |

`starlette` also jumps to `1.6.0` transitively via fastapi — a major
version change not itself listed in any of the PRs, and worth noting
because it, not fastapi, owns the middleware/CORS/session behavior this
app depends on.

**Pre-existing skew discovered (the most useful finding)**

`notifier/requirements.txt` was *already* on `rq==2.12.*` and
`psycopg==3.3.*` while `api` sat on `rq==1.*` and `psycopg==3.2.*` —
despite the two services sharing a Redis queue and enqueuing jobs across
the container boundary **by string path** (`app.jobs.send_test_message`),
which is exactly the pattern most sensitive to an RQ job-payload format
change. This was never deliberate. PRs #22 and #24 close it.

Rather than assume, both directions were proven empirically against a
real notifier worker running rq 2.12: api on rq **1.16.2** → worker
`INTEROP OK`, and api on rq **2.12.0** → worker `INTEROP OK`. So the
skew was *latent* rather than actively broken — but it was a real
cross-version dependency nobody had verified, and aligning the pins
removes it.

**Verification** (disposable containers on the deploy host, per this
project's methodology)

- **A/B harness**: a throwaway Postgres+Redis pod with all `db/0*.sql`
  migrations applied, running the api unit + integration suites against
  a supplied requirements file. Written because
  `api/tests/run_integration.sh` has hardcoded `/tmp/...` paths and
  predates `db/007`. Baseline (master pins) and bumped both give **31
  unit tests passed + `ALL API INTEGRATION CHECKS PASSED`** — identical
  results, with baseline's 4 deprecation warnings gone after the bump.
- **uvicorn 0.30 → 0.52**: booted under the *real* Dockerfile CMD
  (`--proxy-headers --forwarded-allow-ips=*`) rather than a bare
  `uvicorn app.main:app`, since the proxy flags are the part most likely
  to break behind Caddy + Cloudflare Tunnel. `/api/healthz` and
  `/openapi.json` both 200; `X-Forwarded-Proto`/`Host` still honored.
  (Both probed **directly against the container**; `/openapi.json` is
  not reachable through Caddy — see the correction above and §12b.)
- **aiosmtplib 3 → 5** — the largest risk, being a double-major bump
  whose only existing coverage (`tests/test_mailer.py`) is fully mocked
  and therefore validates the *call*, not the real signature or wire
  behavior. Exercised for real against a disposable non-AUTH SMTP sink
  that records what it receives:
  - the magic-link message arrives **intact** — From/To/Subject headers,
    body copy, and the token in the callback URL all verified on the
    receiving end, not merely "no exception raised";
  - `aiosmtplib.send()` still accepts every kwarg `mailer.py` passes
    (`hostname`, `port`, `start_tls`, `username`, `password`);
  - passing a non-None `username` to a relay that doesn't advertise AUTH
    **still raises** under v5, confirming the semantic that
    `api/app/mailer.py`'s empty-string-user guard exists to work around
    is unchanged — so that guard remains both correct and necessary.
    Had v5 quietly changed this, the guard would have become dead code
    and the original empty-`FCCULS_SMTP_USER` bug could have silently
    returned in a different form.

**Note for future dependency rounds**: a green mocked unit test is not
evidence that a major bump of an I/O library is safe. In this round the
mocked mailer tests passed identically on aiosmtplib 3 and 5 while
telling us nothing about either the signature or the AUTH semantics the
production code actually depends on. The real-listener smoke test is
what produced the confidence to merge #26.

Merged to master and deployed via `deploy/update.sh --force` with a
live smoke test, per README's Development / Testing Methodology rule
that dependency and base-image bumps get the same live verification as
any other change and are never auto-merged.

README's Software Bill of Materials was updated to match — that section
is hand-maintained and had gone stale on all five api pins, which is
exactly the drift it exists to prevent. An audit of every other SBOM
entry against its real manifest (`ingestor`/`notifier` requirements,
`web/package.json`, all Dockerfile/compose base-image tags) found no
other mismatches. The api entry also gained two standing notes: that
`starlette` arrives transitively via fastapi (so a major change there
can land without appearing in any Dependabot PR title), and that `rq`/
`psycopg` must be bumped in lockstep with `notifier`, citing the skew
found in this round.

### Personal Radio Services: GMRS, Aircraft, and Ship

Added three more FCC ULS datasets — **GMRS** (`ZA`), **Aircraft**
(Part 87, `AC`), and **Ship** (Part 80, `SA`/`SB`/`SE`) — at full feature
parity with Amateur. The explicit product goal was that users of these
services not be second-class citizens, so everything except the New Hams
celebration (deliberately Amateur-only) works identically: browse, sort,
filter, detail pages, field-definition tooltips, cross-service identity
grouping, search, watches, and notifications.

**Sources were verified live, not assumed.** FCC's `complete/` and
`daily/` directories have listings enabled, which is authoritative and
beat guessing at filenames — `l_aircraft.zip` does not exist, the real
name is `l_aircr.zip`, and FCC returns a **302 redirect rather than a
404** for a missing file, so a naive existence check reports a wrong
filename as present. Record layouts came from FCC's own Public Access
Database Definitions DDL, cross-checked against two independent mirrors
that diffed byte-identical, and then validated by strict-parsing every
row of every complete dump (5,622,629 rows).

**The finding that shaped the design:** `HD`, `EN` and `HS` are
byte-identical in layout across all four license services — they are
generic ULS record types, not Amateur-specific ones. So `schemas.py`'s
`AMAT_*` lists were renamed `ULS_*` (aliases kept), and the 14 new tables
are created with `LIKE amat_hd INCLUDING ALL`, making structural identity
a schema guarantee rather than three hand-transcribed copies that drift.
For the same reason the API and frontend are each driven by a single
config dict (`SERVICE_CONFIGS`, `PERSONAL_SERVICES`) feeding one generic
router and one browse/detail component pair: parity is the goal, and
making it *structural* guarantees it. Adding a fourth service is now a
dict entry, not new files to keep in sync. Amateur deliberately keeps its
own module — operator class, trustee/club and New Hams don't generalize,
and rewriting working code that serves live data would have been risk for
a cosmetic gain.

**Three real parsing hazards were found in the data, all in production
files that would have silently corrupted rows:**

1. **Embedded newlines in `SV.dat`.** 389 of its 1,068 physical lines are
   continuations — the free-text voyage description contains bare `CR`/
   `CRLF`. The old line-oriented parser produced 970 rows of which 291
   were malformed; prefix-aware reassembly yields 679 correct records.
   Applied generically to every file, since it is strictly safer.
2. **Unescaped `|` inside free-text fields.** FCC applies no quoting at
   all, so a typed pipe breaks that row's field count. Only 17 rows in
   5.62M are affected and they are unparseable in principle — tolerated
   via truncate/pad but **logged as a warning** so the damage is never
   silent, with `validate_schema.py` given a 0.1% tolerance so this known
   noise can't be confused with a real layout change.
3. **Double quotes in free text** made `csv.reader` rewrite values *and*
   re-split the newlines reassembly had just repaired. Replaced with a
   plain `raw.split("|")`.

Also: FCC splits one long `SV` description across several
sequence-numbered rows sharing a `unique_system_identifier`, so the
natural key must be composite — a single-column key would collapse each
description to its last fragment on re-ingest.

**Two real bugs were caught by testing that would otherwise have
shipped:**

- **The `watches` unique constraint excluded the new `service` column**,
  which meant a user could not hold both a GMRS-scoped and an
  Amateur-scoped watch on the same callsign and channel — making the
  feature it was added for nearly useless. Fixed with
  `UNIQUE NULLS NOT DISTINCT`. The `NULLS NOT DISTINCT` is essential and
  easy to get wrong: the PostgreSQL default treats NULLs as distinct,
  which would have silently dropped duplicate protection for *unscoped*
  watches — the most common kind. All three behaviours were then proven
  empirically rather than reasoned about.
- **Both `api/tests/run_integration.sh` and
  `notifier/tests/run_integration.sh` hardcoded stale migration lists**
  (stopping at 006 and 005 respectively), so both suites had been quietly
  testing against an out-of-date schema. Replaced with a sorted glob, so
  they cannot go stale again.

Testing followed the project's standard methodology throughout — real
infrastructure in disposable containers on the production host, never
mocks alone. Using a real schema rather than a hand-built fixture also
caught seed data written against guessed column names, which exposed a
genuine FCC inconsistency worth recording: `ship_sh` uses `callsign`
while `ship_sr`/`ship_sv`/`ship_se`/`aircr_ac` all use `call_sign`.

Field definitions were treated as a first-class deliverable, since
undefined codes would produce exactly the second-class experience this
work existed to avoid. Six of seven new coded fields were substantiated
from FCC Form 605 and the FCC code-definitions file. One genuine negative
result is recorded rather than papered over: `SH.working_freq_s1/s2`
have **no published decode table anywhere** — confirmed across FCC
documentation and ten third-party ULS parsers — so they display raw with
a tooltip saying so. Rare junk values in `SH.general_class` (5 codes
cover 99.997% of rows) and `special_class` are likewise left undecoded
rather than guessed.

### New Hams: operator class column

Added an operator-class column to both New Hams components. The
motivating observation was correct and is measurable in production data:
in the current 10-day window, **25 first-time licensees tested straight
into General and 8 into Amateur Extra — over 10% of the feed**. A table
that implied everyone starts at Technician was quietly erasing those
people's achievement.

`/api/new-hams` gains `am.operator_class` via a `LEFT JOIN amat_am`, and
both the homepage widget and `/new-hams` render a Class column. It shows
the **full class name rather than the bare FCC letter**, since the
explicit goal was at-a-glance recognition and a lone `E` communicates
nothing to a casual visitor; the raw code and description remain
available in the tooltip, consistent with the project's field-definition
standard. New `.pill.opclass-*` variants emphasise General and Extra so a
higher-class debut stands out from the Technician majority.

Verified against production before writing the UI: **clubs have no
operator class at all** (all 4 in the window are NULL), so the column
needs a genuine em-dash fallback, and the API deliberately returns the
field present-but-null rather than omitting it so the frontend can tell
"club, not applicable" apart from a missing field. Both cases are
asserted in the API integration test, whose seed row was deliberately
changed to model a straight-to-Extra first timer rather than another
Technician.

### Progress Log — architecture.md audit and the missing parse stage

Audited `docs/architecture.md` end to end rather than only re-reading the
sections touched by the personal-radio-services work, on the theory that
a diagram file drifts silently in places nobody thought to look.

Three real gaps were found. First, **§6's notification pipeline never
mentioned the new per-watch service scope** at all, so the diagram still
described pre-GMRS matching behaviour. Second, and more significantly,
**the parse stage — file to record — was undocumented anywhere**, despite
holding the subtlest correctness logic in the codebase: prefix-based line
reassembly, the deliberate refusal to use `csv.reader`, and the
tolerate-but-log handling of unescaped delimiters. Every one of those
decisions had a hard-won reason recorded only in code comments. That is
now §4, with a flowchart and three explainers, and §2's Level-0 `parse`
and `diff` boxes link into §4/§5 so the drill-down path is discoverable.

Third, **§10's rate-limit list was quietly wrong**: it read "search,
browse, new-hams, auth, admin". Checking `enforce_rate_limit` call sites
showed `personal_services.py` limits *both* browse and detail, while the
older `amateur.py`/`towers.py` limit browse only — so GMRS/Aircraft/Ship
callsign lookups are throttled and Amateur/Tower ones are not. The label
now says so, and an explainer ties the asymmetry to the existing
`mcp-detail-endpoint-rate-limit` todo, which must close before any
unauthenticated MCP surface exposes those two endpoints.

Renumbering old §5–§12 to §6–§13 broke cross-references, so all links
were verified mechanically rather than by eye: a script resolved every
intra-document anchor (13) and every `README.md` link into the file
against the real heading list, catching one stale `[§12]` in
`architecture.md` and two in `README.md`.

All 15 Mermaid diagrams were **actually parsed**, not assumed valid —
extracted and run through `mermaid.parse()` in a disposable `node:22`
container. This mattered: the new §4 diagram embeds literal `|`
characters in node labels (`RECORDTYPE|`, `Split on '|'`), and `|` is
Mermaid's edge-label delimiter. Inside quoted labels it turns out to be
safe, but that was worth proving rather than hoping. (Mermaid needs a DOM
to get past `DOMPurify.addHook`; supplying `jsdom` globals makes headless
validation work and is worth reusing for future diagram edits.)

Every factual claim in the new §4 was re-checked against the source —
the truncate/pad-and-warn behaviour in `parser.py`, and the
`MISMATCH_TOLERANCE = 0.001` figure in `validate_schema.py`. Docs-only
change; `architecture.md` is not baked into any image, so unlike
`user-guide.md` this needs no redeploy.

### Progress Log — unambiguous pagination counters

Reported as a nitpick; it was a real readability bug on every paginated
view. The pager rendered `Page {page} · {total} total`, which on
`/amateur` came out literally as **`Page 1 · 1441106 total`**. Two
separate defects: the two numbers look like a pair but aren't (the
second is the record count, not the page count), and **total pages was
computed nowhere in the codebase** — the one number a reader most
expects was simply absent. Counts were also printed raw; nothing in
`web/src` called `toLocaleString`.

Now: `Page 1 of 67,806 · showing 1–25 of 1,695,148`.

The same markup was copy-pasted **seven times** (amateur, towers,
`ServiceBrowse` → gmrs/aircraft/ship, new-hams, the homepage widget, and
admin's two), each with its own duplicated `page * pageSize >= total`
disable condition. Extracted `web/src/lib/Pagination.svelte`, which owns
that boundary once instead of seven times. The homepage widget passes
`compact` to drop the word "showing" and protect the above-the-fold
constraint it was built around.

Two edge cases the format forced into the open. The chosen wording
degenerates to the nonsense "Page 1 of 0 · showing 0–0 of 0" when
nothing matches, so `total === 0` renders **No results** with both
buttons disabled. More interestingly, `total` is 0 until the first fetch
resolves and these pages set `loading = true` only *inside* `load()`,
which runs from `onMount` — i.e. after first paint. So a naive
implementation flashes "No results" on every page load. The initial
`loading` value is now `true` in all five affected components (which
also makes the pre-existing "Loading…" indicator appear immediately,
and incidentally fixes the same latent flash in the homepage widget's
"No new grants" branch).

Number formatting lives in a shared `lib/format.js` and **pins `en-US`**
rather than calling bare `toLocaleString()`: `web` builds with
`adapter-static`, so markup is prerendered under Node and hydrated in
the browser, and an unpinned locale can format differently in those two
environments.

Verified by **server-rendering the compiled component** against real
totals rather than eyeballing the template — last-page partial ranges
(`Page 57,645 of 57,645 · showing 1,441,101–1,441,106 of 1,441,106`),
single-short-page, both empty states, and both compact cases, each with
the correct buttons disabled. Then a real `vite build` in a disposable
container before deploying, and live verification across all five browse
services plus a deliberate zero-match filter.

One deployment note worth recording: the `deploy/update.sh` run outlived
an SSH disconnect (`client_loop: send disconnect`). The build had already
completed, but the restart loop was still mid-flight, leaving `fcculs-web`
running the previous image while `:latest` had already moved. Comparing
`podman inspect fcculs-web --format '{{.Image}}'` against the `:latest`
image ID is the quick way to detect that drift; the script finished on
its own and the IDs matched afterwards. Re-running `update.sh` in that
window would have reported "Already up to date" and skipped the restart,
since all four images legitimately carried the current revision label.

### Progress Log — MCP server plan refreshed (still not built)

Planning-only, at the user's explicit request: bring §12a into line with
the app as it exists today. No code was written and no todos were
created — the section describes work that is still deferred.

The old draft had gone stale in two independent ways. **Feature-wise**
it only knew about Amateur and Tower, so it silently omitted the
GMRS/Aircraft/Ship browse+detail endpoints, `/api/new-hams`, eight of
the twelve search arms, and the fact that `identity_by_frn` now spans
five services. **Stack-wise** it named `FastMCP`, which no longer
exists.

That second point is why this was verified rather than summarised.
Checked against PyPI and the SDK source at tag `v2.2.0`: `mcp` 2.2.0 is
current, and `src/mcp/server/fastmcp.py` is now a deliberate tombstone
that raises `ModuleNotFoundError` pointing at a migration guide — the
class is `MCPServer`. The current spec revision is `2026-07-28`, which
is sessionless by construction (no `initialize`, no `Mcp-Session-Id`,
so no sticky-session requirement).

Re-checking the proposed stack against the *project* rather than the
SDK turned up a second, separate class of mismatch — the draft asserted
"Python 3.12, matching every other service," but every Python service
moved to `python:3.14-slim` in the Dependabot batch logged earlier, so
3.12 matched nothing. (The SDK supports 3.14 explicitly and ships
3.14-specific `anyio`/`starlette` pins, so no downgrade is needed.)
Corrected alongside it: the base image now carries the
`docker.io/library/` prefix the other Dockerfiles use, and the pin
style follows the existing `==X.Y.*` wildcard-minor convention
(`mcp==2.2.*`) instead of the freeze the draft recommended.

The dependency note was wrong in the same direction. The SDK requires
**`httpx2`**, which is Pydantic's continuation of `httpx` under a new
distribution *and a new import name*, currently 2.12.0 — while upstream
`httpx` sits at 0.28.1, which is what this project pins. The draft
described that as "httpx (v1)", which undersells the problem: the MCP
service would write `import httpx2` while every sibling service writes
`import httpx`, so the notifier's webhook-sender patterns won't
copy-paste. Separate containers mean there's no conflict to resolve,
only a deliberate choice to record.

Two smaller drift items came out of the same pass. The base image now
carries the `docker.io/library/` prefix the real Dockerfiles use, and
the claim that `config.py` would follow "the same convention as
`api`/`notifier`" was collapsing two different things: the shared
convention is the `FCCULS_` env-var *prefix*, but `api` uses
`pydantic-settings` while `notifier` uses a plain dataclass over
`os.environ`.

Checking the stack also surfaced two directory-scoped mechanisms that
would silently skip a fifth service. `.github/dependabot.yml` has no
recursion — it lists an explicit entry per directory per ecosystem, so
a new service needs two new entries or its dependencies and base image
simply never get bumped, with nothing to signal the omission. And the
SBOM in `README.md` is hand-maintained by design, duplicating every
service's manifest in one place for auditors. Both now have a
`mcp-repo-hygiene` todo; neither is something to discover after the
service has been running unpatched for months.

One claim was worth chasing down to the source because a plain reading
of it was **wrong in both directions**. `TransportSecurityMiddleware`'s
own default is DNS-rebinding protection *disabled* — but the app factory
in `lowlevel/server.py` pre-empts that: when `transport_security is
None` **and** `host` is a loopback value, it auto-arms protection with a
localhost-only allowlist. So behind Caddy the endpoint would return
`421 Misdirected Request` for every request, logged server-side only
while the client sees a generic transport error. Two further traps
recorded: the `host=` argument is not the uvicorn bind address (passing
a real hostname there disarms the check rather than allowlisting it),
and constructing `TransportSecuritySettings()` without `allowed_hosts`
enables the check against an empty list, rejecting everything.

Two genuinely new findings came out of auditing the current code rather
than the old plan. First, **`identity.py` has no rate limiting at all** —
it imports no limiter — and those are the most expensive queries in the
app as well as the most attractive to an agent; the old plan only ever
flagged the Amateur/Tower *detail* gap. Note the asymmetry: the
personal-services detail endpoints, built later via the router factory,
*are* limited, so this is an oversight rather than a decision. Second,
`web/src/lib/fieldDefs.js` is 409 lines of code decodings that exist
**only in the frontend**, so an MCP client would receive raw FCC codes
where a human gets a tooltip — reintroducing exactly the second-class
experience the GMRS/Aircraft/Ship round was meant to prevent. Both now
have todos in the section.

Also recorded: a top-level `mcp/` directory would collide with the `mcp`
package name and could shadow the SDK import, so the directory name must
be decided before scaffolding rather than debugged afterwards.

Docs-only; `plan.md` is not baked into any image, so no redeploy.

### 2026-09-07 — MCP server built, tested, and live

`docs/plan.md` §12a's plan is implemented and deployed. The server is at
`https://fcculs-explorer.n00tz.net/mcp` and answers a real MCP client.

**Prerequisites first.** `api/tests/run_integration.sh` was still pinning
`python:3.12-slim` after the Dockerfiles moved to 3.14, and hardcoded its
unit-test list — which had already gone stale and was silently skipping
files. It now globs `tests/test_*.py`. That change immediately surfaced a
failing assertion in `test_field_defs.py` claiming
`applicant_type_code["B"] == "Club"`; the authored source
(`web/src/lib/fieldDefs.js:165`) says `Amateur Club`, so **the test was
wrong, not the generator**. Also closed the last rate-limit gap: the
Amateur and Tower *detail* endpoints, plus both `identity.py` endpoints,
now enforce the shared search tier, verified by asserting real `429`s
rather than testing the helper in isolation.

**The SDK did not match the plan.** Verified by running it, not reading
about it: `MCPServer.__init__` has no `host`/`port`/`transport_security`
parameters — those live on `streamable_http_app()`. `TransportSecuritySettings()`
defaults to `enable_dns_rebinding_protection=True` with an *empty*
allowlist, so the bare constructor rejects everything, while passing
nothing at all auto-arms a localhost allowlist that 421s behind a proxy.
Both implicit paths are wrong; it is now set explicitly. The client helper
is `streamable_http_client` (not `streamablehttp_client`) and yields two
values, not three. Tool objects expose `input_schema`, not `inputSchema`.

Directory named `mcpsrv/`, as flagged in the planning entry, to avoid
shadowing the `mcp` SDK package.

**Eleven tools, not twenty.** Browse and detail are unified behind a
`service` enum rather than one tool per service, keeping the catalog small
enough for a model to reason about. Service-specific filters
(`operator_class`, `n_number`, `ship_name`, `mmsi`) are forwarded *only*
to the service that accepts them — the API rejects unknown query params,
so leaking one would convert an ignorable argument into a hard failure.
Covered by both a unit and an integration test.

**Caught in self-review:** `call_api_tool` was defined but never called,
so `ApiError` would have escaped as an opaque protocol error instead of
the intended `{error, status_code}` payload. A 404 for an unknown callsign
is normal usage, not a failure, and now reads as such.

**Testing.** 12 unit tests plus an integration run driving real MCP
protocol calls through a real `api` and Postgres in a disposable pod.
Debugging it produced one finding worth more than the feature: a CRLF line
ending broke the test script, and the root cause was that the repo had
**no `.gitattributes` at all**, so the Windows worktree held CRLF in 19
files — including `deploy/update.sh`. That is a latent hazard for anyone
cloning on Windows, not a quirk of the new file. Added `.gitattributes`
forcing LF on `*.sh`/`Dockerfile`/`*.container`/`Caddyfile` and normalized
all 19.

**A real bug that only live testing could find.** Everything passed
inside the podman network, but through the public hostname
`https://…/mcp/` redirected to **`http://…/mcp`** — a protocol downgrade
MCP clients refuse to follow. Only the un-slashed path worked. Two
compounding mistakes: `header_up X-Forwarded-Proto {scheme}` forwarded
*Caddy's own* scheme, which is always `http` because Cloudflare terminates
TLS and cloudflared reaches the container over plain HTTP; and simply
deleting that line did not help either, because Caddy deliberately ignores
an incoming `X-Forwarded-Proto` unless the sender is a configured
`trusted_proxy`. (Caddy's own "Unnecessary header_up X-Forwarded-Proto"
warning is actively misleading here.) Confirmed by probing rather than
assuming — Cloudflare *does* send `X-Forwarded-Proto: https` and a
`Cf-Visitor` scheme of `https` while Caddy's `{scheme}` is `http` — and
fixed by matching on that header, which re-asserts the true scheme without
hardcoding cloudflared's IP and leaves genuine plain-HTTP LAN requests
alone. Also corrected a comment that had the redirect backwards: the SDK
mounts at `/mcp` and redirects `/mcp/` → `/mcp`, not the reverse;
`handle /mcp*` was right for the opposite reason to the one documented.

**Live verification** with the real SDK client against production: all 11
tools advertised, `search_uls` and `get_license` returning real data,
cross-service FRN grouping working, all four licence services plus towers
browsing, oversized `page_size` rejected, `describe_code` translating `E`
to `Amateur Extra`, a 404 degrading to a structured error, and an invalid
enum rejected by schema validation. Recorded as `mcpsrv/tests/live_check.py`
so it can be re-run after future deploys. Writing that script also exposed
that two of its own calls used wrong parameter names, one of which had an
assertion weak enough to pass while the call was actually erroring — both
tightened.

`update.sh`'s stale-image check now covers five images, and
`docs/architecture.md` gained a new §11 plus topology/diagram updates. The
architecture doc's claim that detail-endpoint rate limiting was still an
open gap was stale and has been corrected.

Redeploy required: `web` (Caddyfile and the baked-in `/help` guide), plus
the new `mcp` unit.

### Swagger / OpenAPI compatibility — investigated, documented, not built

Investigated what "make the API Swagger compatible" would require. The
user's decision was to **record the design as a deferred feature rather
than build it**, so this round changed documentation only — no code, no
image rebuild, no deploy. The design lives in §12b; this entry records
what was actually measured, because a deferred design gets read much
later by someone who will reasonably trust it without re-checking.

Everything below was probed against the running production stack, not
inferred from the source:

- **The generated docs are unreachable, and a previously recorded
  "accepted risk" was wrong.** The security-hardening entry above stated
  that `/docs`, `/redoc` and `/openapi.json` were deliberately left
  public. They are not public and never were: `web/Caddyfile` proxies
  only `/api/*`, so those paths fall through to the SvelteKit SPA and
  return its `index.html` **with a `200`**. Fetching the body rather than
  trusting the status code is what exposed this. `/api/docs` and
  `/api/openapi.json` return `404`. That paragraph now carries an inline
  correction.
- **`FastAPI(openapi_version="3.0.3")` is silently ignored** on the
  deployed FastAPI 0.141 — constructed in the real `api` image, it still
  reported `3.1.0` and still emitted `anyOf: [{"type":"string"},
  {"type":"null"}]`. This matters disproportionately: it is the obvious
  one-line implementation, it fails without erroring, and assuming it
  works would have produced a spec that lies about its own version.
- **A 3.0.3 downgrade is mechanical, not lossy.** Inventorying every key
  in the real 35 KB document showed the *only* 3.1-specific construct is
  the nullable idiom — 61 `anyOf` members of `{"type": "null"}`. No
  `const`, `prefixItems`, type-arrays, `examples`, `exclusiveMinimum` or
  `contentMediaType`. A prototype transform run against the real spec
  converted all 61 to `nullable: true`, left **zero** residual
  `"type": "null"`, and preserved all 34 paths and every component
  schema.
- **The spec is structurally thin.** 18 of 26 `GET` endpoints declare a
  completely untyped `{}` `200` response — every detail endpoint,
  `search`, both `identity` endpoints, `field-definitions`, `watches`,
  `channels`, `auth/me` and `healthz`. `Page.items` is `array of {}`, so
  even the typed endpoints stop at the wrapper. There are no
  `securitySchemes` despite cookie-based user *and* admin sessions, and
  only `200`/`422` are documented although `404` and `429` were both
  observed firing live during the MCP work.

One verification could **not** be completed and is deliberately left as
an acceptance criterion rather than being written up as settled: the
downgraded document was never checked by an independent validator
(`openapi-spec-validator`), because installing it was out of scope for a
documentation-only change. "No residual 3.1 constructs" is a weaker claim
than "a real validator accepts it," and §12b's testing section requires
closing that gap before the 3.0 document is considered done.

No redeploy required — documentation only.

### Homepage: MCP surfaced as a first-class feature

The MCP server had been live at `/mcp` since §12a and fully documented in
`docs/user-guide.md`, but the homepage never mentioned it — so the only
people who could discover it were those already reading the help page.
The user's call was that it belongs at the same level as the notification
service, and that the **"🔎 Browse & search"** card should give up its
slot for it.

What changed (`web/src/routes/+page.svelte`, `web/src/app.css`,
`docs/user-guide.md`):

- **New "🤖 Ask an AI assistant" card**, placed last so the grid reads
  browse → notify → ask. It names the transport (`/mcp`), gives two
  concrete example questions, and enumerates what the tools actually do —
  each claim checked against the live tool list rather than written from
  memory: search, browse, license/tower detail, FRN **and address**
  grouping, `describe_code`, and change history. It states plainly that
  the server is read-only, exposes only already-public data, and needs no
  account or key, then links to
  `/help#using-this-site-with-an-ai-assistant` for setup.
- **The removed card's content was folded into its neighbour** rather
  than dropped. Deleting "Browse & search" outright would have taken the
  only mention of sortable columns and per-field filters off the homepage,
  so the identity card became **"🕸️ Browse & discover related
  identities"** and absorbed that sentence.
- **The hero paragraph** gained a closing clause so all three pillars are
  still previewed above the fold.
- **`.feature-card p + p`** — the existing rule is `p { margin: 0 }`,
  which assumed one paragraph per card. The AI card is the first with
  two, so without this the paragraphs butt together. `.feature-card code`
  mirrors `.markdown-body code`, since no global `code` style exists.
- **`docs/user-guide.md`'s "The home page"** section enumerated the three
  cards by name and would have gone stale immediately; it now lists the
  new set and cross-links the AI-assistant section.

Verified with a real `vite build` in a disposable `node:26-slim`
container on the host (matching `web/Dockerfile`'s build stage), which is
non-negotiable here — an invalid Svelte binding once shipped a silently
stale production image in this project. **A green build was explicitly
not treated as sufficient**: the homepage is not prerendered (`grep` for
existing card text in `build/index.html` returns nothing — it's an SPA
shell), so the built JS chunk was searched directly. Confirmed in
`_app/immutable/nodes/2.*.js`: the new card text and the
`using-this-site-with-an-ai-assistant` anchor are present, the old
"Browse & search" string is gone from every chunk, and both new CSS rules
are in the emitted stylesheet.

Redeploy required — this is a web change, and `docs/user-guide.md` is
baked into the web image at build time.

### 2026-09-08 — Continuous ingest: polling FCC every 15 minutes

The ingestor's once-daily `CronTrigger(hour=13, minute=30)` is retired in
favour of an `IntervalTrigger` poll. See §3a of `docs/architecture.md`
for the resulting design.

**This is a latency fix, not a correctness fix**, and it is worth being
precise about that. The catch-up logic already self-heals inside FCC's
rolling 7-day window, so no data was ever being lost. What was bad was
the tail: a file published at 12:00 UTC waited 1.5 h, but a file
published at 14:00 UTC — *after* the run — waited until 13:30 the next
day, roughly **23.5 h**. Polling collapses that worst case to ~15 min and
turns FCC's irregular publication into a non-event. Nothing here should
be described as fixing data loss.

**The server was probed rather than assumed, and three of the four
findings contradicted the obvious implementation.**

1. **`If-Modified-Since` is honoured; `If-None-Match` is not.** Echoing
   FCC's own ETag back returns `200` with a full body. The intuitive
   ETag-based conditional request would have transferred the entire
   listing every poll while looking perfectly correct in logs and tests.
2. **Listing timestamps are US Eastern, not UTC.** `l_amat.zip` reads
   `2026-09-06 09:08:06` in the listing against `13:08:06 GMT` by HEAD.
   This is converted with `ZoneInfo("America/New_York")` and **not** a
   fixed −4, because every timestamp on the server today is summer time:
   a constant offset passes every test writable now and then misdates
   every file after 1 November. That is pinned by an explicit DST test
   rather than left to be discovered in production.
3. **The listing is a static `index.html`, not live autoindex output.**
   It was observed describing files published at 08:00–08:06 EDT while
   its own mtime was 10:15:09 EDT — lagging by over two hours. So
   index-only polling *cannot* guarantee detection within one interval,
   which is the entire objective. This single finding is why the design
   is a hybrid (cheap listing GET as trigger + targeted HEADs for dates
   actually outstanding) instead of the simpler, cheaper index-only
   version that was the starting assumption.
4. **Live observation added afterwards:** the listing is regenerated
   **hourly at ~:15** (`14:15:09` then `15:15:18` UTC). So one poll an
   hour legitimately sees a `200` and the other three see `304`s. Worth
   recording because a `200` at :15 looks like a broken conditional
   request if you don't know this.

**Cost is the reason for the whole design.** A naive 15-minute sweep of
the existing per-file HEADs would mean 35 requests × 96 polls:

| Mode | Per poll | Per day |
|---|---|---|
| Old daily cron | 35 | 35 |
| Naive 15-min per-file sweep | 35 | ~3,360 |
| This design, caught up | 1 (a `304`) | ~96 |
| This design, waiting on a publication | 1 + ≤5 | ~340 |

Going from 35 to ~3,360 requests/day against a government server was not
acceptable, and rate-limiting ourselves out of the data would have been a
self-inflicted outage. The listing is 18,124 B raw / **3,465 B gzipped**,
and its parse was checked against real HEADs for all 35 daily files:
**0 mismatches** on both timestamp and size.

**The advisory lock exists to protect users, not the database.**
`change_events` has no unique constraint, and `differ.diff_rows()`
compares each row against the *currently stored* row — so two overlapping
ingests of the same day each emit a full set of events, and the notifier
faithfully turns those into **duplicate emails, texts and webhooks**.
That was nearly impossible at one run per day and entirely plausible at
96. `pg_try_advisory_lock` is used deliberately over the blocking form: a
poll that finds an ingest already running should step aside, not queue
behind it and then redo the work. It is session-scoped, so a crashed
ingestor releases it automatically.

**FCC's own `counts` member turned out to be a genuine integrity
oracle.** Every archive carries one, and its per-file row counts matched
production exactly — amateur 2026-09-01 at **5,691** and ship 2026-09-02
at **219**, across different services and different record-type sets.
Three gotchas are baked into the parser and its tests: the file uses CRLF
and a space-padded day; its timezone is an *abbreviation* that `%Z`
cannot portably parse, so it is captured, discarded, and re-interpreted
in Eastern; and the `total` line must **never** be compared against,
because it counts record types this project deliberately skips (`CO`,
`SC`, `LA`, `SF`) and would produce a permanent false mismatch. A
mismatch logs a `WARNING` and records `status='partial'` — never a
refusal to ingest, because the known FCC quirks this is meant to surface
(embedded newlines in `SV`, unescaped `|`) would otherwise block
perfectly valid data.

`counts` also closed a real hole: `File Creation Date` equals
`Last-Modified` exactly, so a file whose header is missing can now be
dated and ingested. Previously such files were skipped **forever**, which
is precisely the wrong failure mode under an "FCC is unreliable" premise.

**Empty archives are normal, not failures.** `l_am_sun.zip` and
`l_am_mon.zip` were both **212 bytes** — valid zips containing only
`counts` and no `.dat` at all (Labor Day and a Sunday). Roughly 2–3 of
every 7 days look like this. They are recorded as zero-row successes;
treating "no `.dat`" as an error would have retried them every 15 minutes
forever.

**A pre-existing harness bug surfaced en route.**
`ingestor/tests/run_integration.sh` never applied `db/008`, so the real
Postgres it tested against was missing `change_events.service` — a column
`ingest.py` has been writing since the personal-radio-services work.
Every integration run had been passing while testing a schema production
does not have. Not caused by this change; fixed here (008, 009 and 010
are now applied) and called out because it means earlier integration
green was worth less than it appeared.

**Testing.** The ingestor suite went **57 → 89 tests**. One existing test
failed legitimately: it encoded the old "skip undateable files forever"
contract, and was rewritten to assert the new deferral behaviour rather
than patched to keep passing. Integration adds a check that opens **two
real Postgres sessions** and proves the advisory lock admits exactly one
ingest — the regression test that actually protects users from duplicate
alerts.

Deferred and recorded in §12: `REFRESH MATERIALIZED VIEW ...
CONCURRENTLY` cannot be adopted, because it requires a unique index and
`identity_by_frn` is a `UNION ALL` carrying **10,165 duplicate rows** on
`(frn, source, subject_key)` out of 2,311,553. This matters more now than
before: refreshes rise from ~1/day to ~2–3/day, since tower (~05:00 UTC)
and amateur/GMRS (~12:00 UTC) no longer coalesce into a single run.

Commit `6174d98`. Only the `ingestor` image needed rebuilding.

**Live verification on production**, because a green test suite has never
been sufficient in this project and the whole point of the change is a
behaviour that only exists against the real server:

- **Steady state is one request and zero bytes.** Two consecutive ticks
  (15:45, 16:01) logged exactly `GET .../daily/ "HTTP/1.1 304 Not
  Modified"` and nothing else — no ingest job, no HEADs, returning at the
  fast path as designed.
- **The full sweep at 60 min** (16:16) dropped the conditional header,
  got a `200`, and evaluated **all five services across all 35 daily
  files from that single response** — zero HEAD requests. That is the
  35→1 cost reduction demonstrated live rather than argued from the code.
- **The hourly heartbeat** reported `5 poll(s) in the last hour, 0
  resulted in ingestion, 0 consecutive failure(s)`, confirming idle polls
  really are silent at INFO while remaining observable.
- **Jitter is working** — ticks landed at :29:44, :45:41, :01:38, :16:49
  rather than on the quarter-hour.
- **A manual `--catch-up` against the live database was a clean no-op**:
  `change_events` was 15,570 before and 15,570 after, delta **0**.
- `--status` reports all five services × 7 days `[ingested]`.

One thing that initially looked like a bug and was not: the first
interval tick returned `200` rather than `304`. Probing the server showed
the listing had genuinely been regenerated at `15:15:18 GMT`, *after* the
startup poll cached its value — which is finding 4 above, and the reason
that finding is recorded at all.

## 12. Future Features (Deferred)

Explicitly out of scope for now, per the user, but worth keeping visible
so they aren't lost or accidentally reinvented differently later:

- **All other public FCC ULS service databases** beyond the five now
  ingested (Amateur, ASR Tower, GMRS, Aircraft, Ship) — e.g. commercial
  land-mobile, broadcast, microwave. Same daily/weekly transaction-file
  ingestion model this project already uses, extended to more `l_*`/`r_*`
  dataset definitions. The GMRS/Aircraft/Ship round made this
  substantially cheaper: adding a service is now largely a config-dict
  entry on both the API and frontend sides rather than new hand-written
  modules.
- **`REFRESH MATERIALIZED VIEW ... CONCURRENTLY`** for the three
  identity/aggregation views. Today's refresh takes an `ACCESS EXCLUSIVE`
  lock for ~21.5 s total (`identity_by_frn` 6.5 s, `towers_by_site` 0.9 s,
  `entities_by_address` 14.1 s, all measured on production), blocking the
  detail pages that read them. `CONCURRENTLY` would avoid that lock but
  **requires a unique index, and one cannot currently be created**:
  `identity_by_frn` is a `UNION ALL`
  (`db/009_identity_views_all_services.sql`) carrying **10,165 duplicate
  rows** on `(frn, source, subject_key)` out of 2,311,553 — verified by
  query. Fixing it means changing the view definition itself, which is its
  own change with its own correctness risk, so it was explicitly left out
  of the 15-minute-polling work. It became slightly more relevant with
  that change, since refreshes went from ~1/day to ~2–3/day (tower
  publishes ~05:00 UTC, amateur/GMRS ~12:00 UTC, so they no longer
  coalesce into a single nightly run).
- **An MCP (Model Context Protocol) server** — ✅ **built and deployed.**
  See "§12a. MCP Server" below for the design, and the
  "2026-09-07 — MCP server built, tested, and live" Progress Log entry for
  what actually changed versus the plan.
- **A Swagger/OpenAPI-compatible published API contract** — the API is
  FastAPI, so a spec is generated internally, but none of it is reachable
  through Caddy today and the document that *is* generated is too thin to
  be useful to third-party tooling (18 of 26 `GET` endpoints declare an
  untyped `{}` response, there are no security schemes, and only
  `200`/`422` are documented). See "§12b. Swagger / OpenAPI Compatibility"
  below for the verified findings and design. **Not built.**
- **Address normalization for identity grouping** — `entities_by_address`
  builds its `address_key` from nothing but
  `lower(trim(street_address))|lower(trim(city))|upper(trim(state))|left(zip_code,5)`
  (`db/009_identity_views_all_services.sql:46-85`), so any spelling or
  abbreviation variant silently splits one household into separate
  groups. **Confirmed against live production data, not hypothesised**: a
  married couple at one address returns two disjoint single-member
  groups, because the FCC free-text values differ in three ways at once —

  | Stored value | `address_key` |
  |---|---|
  | `509 Mt View Dr`, `Tunnell Hill` | `509 mt view dr\|tunnell hill\|GA\|30755` |
  | `509 Mountain View Drive`, `Tunnel Hill` | `509 mountain view drive\|tunnel hill\|GA\|30755` |

  `Mt`/`Mountain`, `Dr`/`Drive`, and a misspelled city (`Tunnell`). The
  failure is **silent** — the affected detail page shows an empty
  "related identities" panel that looks identical to a genuinely
  unrelated licensee, so nobody is prompted to doubt it. Note the
  equivalent FRN-based grouping is unaffected and worked correctly for
  the same records; this is specific to the address path.

  A fix would normalize before hashing: expand USPS street-suffix and
  directional abbreviations (`Dr`→`Drive`, `Mt`→`Mountain`, `N`→`North`),
  strip punctuation, and — since the city name itself can be misspelled
  while the ZIP is authoritative — consider dropping `city` from the key
  entirely and relying on `zip5` + normalized street, which would have
  grouped the pair above correctly. Worth measuring the false-*merge*
  rate before committing to that, since apartment/unit numbers live in
  the same free-text field and over-normalizing could group unrelated
  neighbours in one building. **Not built.**

## 12a. MCP Server — Design (BUILT — live at `/mcp`)

**Status: implemented and deployed.** This section is retained as the
design record. Where the SDK's real API differed from what was planned
here — and it differed in several places — the Progress Log entry
"2026-09-07 — MCP server built, tested, and live" is authoritative.
Notably, the shipped tool surface is **eleven** tools using a unified
`service` enum, not the per-service pairs sketched below, and the
directory is `mcpsrv/`.

**Last refreshed** after the GMRS/Aircraft/Ship, New Hams, and
pagination rounds. The original draft of this section predated those
features and only covered Amateur + Tower; it is now aligned with the
API surface that actually exists today, and the SDK facts below were
re-verified against PyPI and the SDK source rather than carried
forward from the earlier draft (which had gone materially stale — see
"Stack" below).

### Confirmed decisions (from user)

- **Scope: read-only.** Search, browse, detail/attribute lookup,
  identity-grouping/crosslinks, and change-history tools only. No
  watch-creation, no notification-channel management, no admin
  actions exposed via MCP. This means **no new auth model is strictly
  needed** — every tool an MCP client can call maps to data that's
  already public/anonymous in the existing REST API. This was the
  single biggest scope-reducing decision: it eliminates the hardest
  open question (how an LLM agent would authenticate as a specific
  human user for magic-link-gated actions) entirely, for now.
- **Transport: remote HTTP**, hosted alongside the rest of the app and
  reachable through the existing Cloudflare Tunnel, so any MCP-capable
  client on the internet can point at it — not just local processes on
  the user's own machine.
- **Deployment: new containerized service** with its own Quadlet,
  calling the existing `api` container over the internal Podman
  network — not mounted inside the `api` FastAPI process. This keeps
  the MCP protocol dependency, its release cadence, and its crash
  blast-radius isolated from the main API, matching this project's
  existing one-container-per-concern pattern (`api`, `notifier`,
  `ingestor`, `web`).

### Why "thin translation layer," not new data-access code

The `api` service already has every read capability this server would
expose, built and tested. The MCP server should therefore contain
**zero direct database access** — it is purely an MCP-protocol-speaking
adapter that calls the existing REST endpoints over the internal
Podman network (e.g. `http://fcculs-api:8000`) and reshapes JSON into
MCP tool results. This avoids duplicating SQL in a second place and
inherits the API's existing validation, rate limiting, and Postgres
pooling for free.

### Tool catalog — all five services, not two

The original draft of this section covered Amateur and Tower only. The
service now ingests **five** datasets, and the tool surface must match
or the MCP client sees an arbitrary subset of the app:

| Existing REST endpoint | MCP tool |
|---|---|
| `GET /api/search?q=` (12 UNION arms — see below) | `search_uls(query, limit)` |
| `GET /api/amateur` | `browse_amateur(filters, sort, page)` |
| `GET /api/amateur/{call_sign}` | `get_amateur_license(call_sign)` |
| `GET /api/towers` | `browse_towers(filters, sort, page)` |
| `GET /api/towers/{registration_number}` | `get_tower(registration_number)` |
| `GET /api/gmrs` | `browse_gmrs(...)` |
| `GET /api/gmrs/{call_sign}` | `get_gmrs_license(call_sign)` |
| `GET /api/aircraft` | `browse_aircraft(...)` |
| `GET /api/aircraft/{call_sign}` | `get_aircraft_license(call_sign)` |
| `GET /api/ship` | `browse_ship(...)` |
| `GET /api/ship/{call_sign}` | `get_ship_license(call_sign)` |
| `GET /api/identity/frn/{frn}` | `get_identity_group_by_frn(frn)` |
| `GET /api/identity/address` | `get_identity_group_by_address(...)` |
| `GET /api/new-hams` | `get_new_hams(page, type)` |
| *(no endpoint exists yet — genuinely new code)* | `get_change_history(subject_type, subject_value)` |
| *(no endpoint exists yet — frontend-only data)* | `describe_code(field, value)` |

Notes on the ones that aren't obvious:

- **The three personal-radio services come from one router factory.**
  `api/app/routers/personal_services.py` builds the GMRS/Aircraft/Ship
  routers from a `SERVICE_CONFIGS` dict. The MCP layer should mirror
  that: generate the six tools from one config table rather than
  hand-writing three near-identical pairs, so adding a sixth ULS
  service later stays a config-dict entry on this side too.
- **Search is 12 arms, not 4.** `_SEARCH_ARMS` in `search.py` covers a
  callsign/registration arm and an entity-name arm for each of the five
  services, **plus two service-specific real-world identifiers**:
  `aircraft_n_number` (FAA tail number, from `aircr_ac.n_number`) and
  `ship_name` (from `ship_sh.ship_name`). The `search_uls` tool's
  docstring must enumerate all of these, because the docstring *is* the
  tool description the model reasons over — an LLM that doesn't know it
  can search by tail number or vessel name simply won't.
- **`identity_by_frn` now spans all five services**, so an FRN lookup
  surfaces a person's entire FCC footprint in one call (135,619 FRNs
  hold both an Amateur and a GMRS licence). This is arguably the single
  most valuable tool in the set for an agent, and worth saying so in its
  description.
- **`get_new_hams`** returns dual totals (`total_individuals` /
  `total_clubs`) over a rolling 10-day window, not the generic `Page`
  shape — its output model must reflect that rather than reusing the
  browse pagination shape.

### `describe_code` — a real parity gap worth closing

`web/src/lib/fieldDefs.js` is **409 lines of code decodings**
(operator class, status codes, applicant type, vessel type, carrier
type, and so on) that exist **only in the frontend**. Server-side there
is just `api/app/history_codes.py` (54 lines, HS log codes).

Consequence: an MCP client calling `get_amateur_license` receives raw
FCC codes with no way to interpret them, while a human on the website
sees a tooltip explaining each one. That is exactly the second-class
experience the GMRS/Aircraft/Ship round existed to avoid, reintroduced
through a different door.

Two options, to be decided at build time:

1. Add a `describe_code(field, value)` tool plus a small
   `GET /api/field-definitions` endpoint, moving the decoding table (or
   a generated copy of it) server-side so both the web UI and MCP
   consume one source of truth.
2. Have the detail tools inline a `*_description` alongside each coded
   field in their MCP output, so the model never has to make a second
   call.

Option 2 is friendlier to an LLM (no extra round trip, no chance of
skipping the lookup); option 1 is less duplication and also fixes the
fact that the decoding table is currently unavailable to any non-browser
consumer. A hybrid — endpoint as the source of truth, inlined at
render time — is likely correct. Either way this is **new work, not a
passthrough**, and should not be discovered mid-implementation.

### Stack — re-verified, and materially changed since the last draft

The earlier draft of this section named `FastMCP` from the official
`mcp` Python SDK. **That is now wrong.** Verified directly against PyPI
and the SDK source at tag `v2.2.0`:

- `mcp` **2.2.0** is the current release (`requires_python >=3.10`).
- **`FastMCP` no longer exists.** `src/mcp/server/fastmcp.py` is now a
  deliberate tombstone that raises `ModuleNotFoundError` on import,
  pointing at the migration guide. The class is now **`MCPServer`**,
  imported as `from mcp.server.mcpserver import MCPServer`.
- The current spec revision is **`2026-07-28`**, which the SDK
  implements. On that revision there is **no session and no
  `initialize` handshake** — a request is one self-contained POST, so
  there is no `Mcp-Session-Id` and no sticky-session requirement. (The
  `stateless_http=` flag is a legacy-clients-only knob and does *not*
  govern the modern path.)
- The SDK pulls in **`httpx2>=2.5.0`** — note the package name, and
  don't skim past it. `httpx2` (currently 2.12.0) is Pydantic's
  continuation of `httpx` under a **new distribution and new import
  name**; upstream `httpx` remains at 0.28.1. This project pins
  `httpx==0.28.*` in `api` and `notifier`, so the MCP service will end
  up with `import httpx2` alongside a codebase that everywhere else
  writes `import httpx`. Copy-pasting the notifier's webhook-sender
  patterns will not work unmodified. Decide deliberately whether the
  MCP client code uses the transitively-supplied `httpx2` or adds an
  explicit `httpx==0.28.*` pin for consistency with its sibling
  services — separate containers mean there's no dependency conflict to
  resolve either way, only a readability choice.
- Dependencies also include `pydantic>=2.12.0`, `jsonschema`,
  `pyjwt[crypto]`, `uvicorn>=0.31.1`, and a pinned `mcp-types==2.2.0`.
- **Python 3.14 is explicitly supported** (it's in the trove
  classifiers, and the SDK carries 3.14-specific pins —
  `anyio>=4.10` and `starlette>=0.48.0` on 3.14 versus looser bounds
  below it). This matters because the earlier draft of this section
  said "Python 3.12, matching every other service", which was
  **doubly wrong**: the project migrated to `python:3.14-slim` in the
  Dependabot batch recorded above, and 3.12 wouldn't have matched
  anything. No downgrade is needed to adopt the SDK.

| Concern | Choice | Rationale |
|---|---|---|
| Language/runtime | Python 3.14, matching `api`/`ingestor`/`notifier` | SDK requires ≥3.10 and ships 3.14-specific dependency pins |
| MCP SDK | `mcp` 2.x, `MCPServer` class | Handles JSON-RPC framing, tool schema generation from type hints/docstrings, and the HTTP transport loop |
| HTTP client to `api` | `httpx2` (transitive) or an explicit `httpx==0.28.*` — pick one deliberately | Sibling services all use `httpx==0.28.*`; the SDK forces `httpx2` into the image regardless |
| Container base image | `docker.io/library/python:3.14-slim`, non-root `USER` | Matches `api`/`notifier`/`ingestor` exactly, including the fully-qualified registry prefix rootless Podman wants |

**Version-pin style:** follow the existing convention rather than
inventing a new one. `api` and `notifier` pin with wildcard minors
(`fastapi==0.141.*`, `httpx==0.28.*`, `psycopg[binary]==3.3.*`), so
this service should use **`mcp==2.2.*`** — not a bare `mcp` and not a
fully-frozen `mcp==2.2.0`. (`ingestor` uses `>=` floors instead; the
`==X.Y.*` style is the better match here given the caveat below.)

**Version-pin caution:** `mcp` 2.2.0 was published on 2026-09-07 — the
same day this section was written — and 2.x is a hard break from 1.x.
Expect Dependabot to open bumps that need the migration guide read
before merging, rather than the usual rubber-stamp. Anyone who instead
wants the old `FastMCP` API must pin `mcp<2`.

### New repo layout

- `mcp/` — new top-level service directory, sibling to `api`/
  `notifier`/`ingestor`/`web`:
  - `app/server.py` — `MCPServer` instance and tool registrations.
  - `app/client.py` — thin async HTTP wrapper over the `api` REST
    endpoints (base URL from a new `FCCULS_API_BASE_URL` setting,
    defaulting to the internal Podman DNS name); see the
    `httpx`-vs-`httpx2` note above before writing it.
  - `app/services.py` — the config table that generates the
    GMRS/Aircraft/Ship tool pairs, mirroring `personal_services.py`.
  - `app/config.py` — the shared convention across services is the
    `FCCULS_` env-var **prefix**, not a shared mechanism: `api` uses
    `pydantic-settings` (`env_prefix="FCCULS_"`), while `notifier`
    uses a plain `dataclass` reading `os.environ`. Either fits.
    `pydantic-settings==2.*` (matching `api`'s pin) is the natural
    pick here since the SDK already forces `pydantic>=2.12` into the
    image, so it costs nothing extra.
  - `requirements.txt`, `Dockerfile` (non-root), `tests/`.

> **Directory-name hazard:** a top-level `mcp/` directory shares its
> name with the `mcp` PyPI package. Depending on how the container's
> working directory lands on `sys.path`, `import mcp` could resolve to
> the local directory instead of the installed SDK. Either keep the
> package root as `mcp/app/` and never add `mcp/__init__.py`, or name
> the directory something non-colliding (`mcp-server/`, `mcpsrv/`).
> Decide this **before** scaffolding, not after debugging an import
> error.

### Repo-hygiene wiring a new service directory requires

Adding a fifth service directory isn't just a Dockerfile — two existing
mechanisms are directory-scoped and will silently skip it otherwise:

- **`.github/dependabot.yml` does not recurse.** It carries an explicit
  entry per directory *per ecosystem* — currently four `pip`-or-`npm`
  entries and four `docker` entries for `/api`, `/notifier`,
  `/ingestor`, `/web` (the file's own comments call out that neither
  the `pip` nor the `docker` ecosystem recurses). A new service needs
  **two** new entries, or its `requirements.txt` and base image will
  never be bumped and the gap won't announce itself.
- **The SBOM in `README.md` is hand-maintained.** It deliberately
  duplicates every service's dependency manifest in one place so an
  auditor doesn't have to open each file, and its own instructions say
  to update it whenever a `requirements.txt` or base-image tag changes.
  A new service adds a new section there.

### Deployment wiring — verified gotchas

- New `quadlet/fcculs-mcp.container`, modeled on
  `fcculs-notifier.container`; new settings threaded through
  `deploy/install-quadlets.sh`'s substitution list; `.env.example`
  documented inline — all the existing conventions.
- **Caddy route:** proxy **both `/mcp` and `/mcp/`.** The SDK's default
  mount path is `/mcp` (`streamable_http_path`), and it issues a
  `/mcp` → `/mcp/` redirect. If uvicorn doesn't know it's behind TLS,
  that redirect points at `http://`, and MCP clients **refuse to follow
  it** rather than downgrade the connection.
- **Run uvicorn with `--proxy-headers` and `--forwarded-allow-ips`**
  set to the proxy address, for exactly the reason above. Note the `api`
  service already had to solve this same class of problem for the admin
  cookie's `Secure` flag (see the security-hardening round) — same
  Caddy + Cloudflare Tunnel chain, same fix.
- **DNS-rebinding protection is the go-live trap.** Verified in
  `src/mcp/server/lowlevel/server.py`: when `transport_security is None`
  **and** the `host=` argument is one of `127.0.0.1` / `localhost` /
  `::1`, the app **auto-arms** DNS-rebinding protection with a
  localhost-only allowlist. Behind a real hostname every request then
  returns **`421 Misdirected Request`**, with the reason logged
  server-side only — the client just sees a generic transport error.
  Three important details:
  - The `host=` argument to the app factory is **not** the uvicorn bind
    address; passing a real hostname there does not allowlist it, it
    merely disarms the auto-enable so *everything* is accepted.
  - `TransportSecurityMiddleware`'s own default (used when settings are
    absent) is protection **disabled** — so the "secure by default"
    behavior comes from the app factory, not the middleware.
  - Constructing `TransportSecuritySettings()` without populating
    `allowed_hosts` enables the check against an empty allowlist, which
    rejects *everything*. This is the easiest way to brick the endpoint.

  Behind Caddy, which already controls the `Host` header, the SDK docs
  explicitly bless
  `TransportSecuritySettings(enable_dns_rebinding_protection=False)` as
  "the honest configuration". Whichever is chosen, it must be an
  explicit, commented decision in `server.py` — not a default nobody
  looked at.
- **Consider `json_response=True`.** It answers each POST with a single
  JSON body instead of an SSE stream, which is friendlier to a
  buffering proxy and to Cloudflare Tunnel's idle-timeout behavior. The
  cost (loss of per-call progress notifications and the back-channel) is
  irrelevant to a read-only server with fast tools.
- **Do not `Mount()` the MCP app inside another Starlette/FastAPI app**
  without hoisting its lifespan — the sub-app's lifespan never runs and
  the first request fails with `Task group is not initialized`. Since
  the decision here is a standalone container, this only matters if that
  decision is ever revisited.
- **Health endpoint:** `@mcp.custom_route("/health", methods=["GET"])`.
  Note these custom routes are deliberately **never authenticated**,
  which is fine for `/health` and must not be used for anything else.

### Prerequisite: close the rate-limiting gaps first

Exposing an unauthenticated, agent-driven tool surface over the public
internet makes the API's existing throttling gaps materially worse — an
LLM client can trivially issue calls in a tight loop. Verified against
the current code:

| Router | Browse | Detail |
|---|---|---|
| `amateur.py` | rate-limited | **not limited** |
| `towers.py` | rate-limited | **not limited** |
| `personal_services.py` (gmrs/aircraft/ship) | rate-limited | rate-limited |
| `search.py`, `new_hams.py` | rate-limited | — |
| `identity.py` | **no rate limiting at all** | **no rate limiting at all** |

Two distinct problems:

1. **Amateur and Tower detail endpoints are unthrottled**, while the
   three newer services' detail endpoints (built later, via the router
   factory) *are*. This asymmetry is an oversight, not a design
   decision, and is already tracked as `mcp-detail-endpoint-rate-limit`.
2. **`identity.py` imports no rate limiter whatsoever** — neither
   `/api/identity/frn/{frn}` nor `/api/identity/address` is throttled.
   The original draft of this section never flagged this, and these are
   the *most* expensive queries in the app (cross-service materialized
   view lookups) as well as the most attractive to an agent. This needs
   its own todo.

### Open items to resolve at build time

1. **`get_change_history` endpoint shape** — nothing exposes
   `change_events` over REST today; detail pages render it inline via
   the routers' own queries. Needs decisions on pagination, date-range
   filtering, and whether `subject_type` is validated against the same
   allow-list `watches.py` uses (which now includes `frn` and
   `asr_registration_number`, and carries an optional `service`).
2. **`describe_code` vs. inlined descriptions** — see above.
3. **Tool result size limits.** MCP has *no* protocol-level limit on
   `tools/call` output and the SDK does no truncation; pagination in the
   protocol applies only to `list_*` methods. Per-tool
   `Annotated[int, Field(ge=1, le=...)]` `limit` parameters plus
   explicit truncation are entirely the server's job, and defaults
   should be **smaller** than the web UI's 25/page — an LLM context
   window is the real constraint.
4. **Access control.** Read-only and unauthenticated was the explicit
   choice, matching the app's already-public search/browse surface. If
   that's revisited, the idiomatic path is a `TokenVerifier` +
   `AuthSettings` pair (a shared bearer token is the SDK's own
   documented example); note the two must be passed together or
   construction raises, `validate_token_resource=True` should be set
   explicitly, and `resource_server_url` must exactly match the public
   Cloudflare hostname + `/mcp`.
5. **Tool annotations.** Mark every tool
   `ToolAnnotations(read_only_hint=True, open_world_hint=False)` — but
   treat these as hints for client UX, never as enforcement.
6. **Structured output.** The SDK derives `outputSchema` from the return
   type annotation and *validates* returns against it, so returning
   typed models gets machine-readable results for free. Watch the silent
   trap: a class with no class-body annotations yields no schema and
   falls back to `repr()` with no warning.

### Todos (tracked in the SQL `todos` table, all `blocked` until this is greenlit)

- `mcp-server-scaffold` — New service directory (name chosen to avoid
  the `mcp` import collision): `MCPServer` instance, config, non-root
  Dockerfile on `docker.io/library/python:3.14-slim`, and requirements
  pinned `mcp==2.2.*` in the project's existing wildcard-minor style.
- `mcp-tool-search-browse` — `search_uls` (documenting all 12 search
  arms including `n_number`/`ship_name`), plus browse+detail tools for
  **all five** services, with the GMRS/Aircraft/Ship six generated from
  one config table.
- `mcp-tool-identity-grouping` — `get_identity_group_by_frn` and
  `get_identity_group_by_address`, both now spanning five services.
- `mcp-tool-new-hams` — `get_new_hams`, respecting the dual-total
  response shape and the 10-day window.
- `api-field-definitions` — Move/expose `fieldDefs.js`'s decodings
  server-side and decide inline-vs-tool, so MCP clients don't receive
  undecodable raw FCC codes.
- `mcp-tool-describe-code` — The corresponding tool (or the inlining
  work, depending on the decision above).
- `api-change-history-endpoint` — New read-only history endpoint on the
  `api` service (genuinely new code, not a passthrough).
- `mcp-tool-change-history` — The tool backed by that endpoint.
- `mcp-detail-endpoint-rate-limit` — Close the gap on
  `GET /api/amateur/{call_sign}` and
  `GET /api/towers/{registration_number}`, bringing them in line with
  the personal-services detail endpoints.
- `api-identity-rate-limit` — Add rate limiting to `identity.py`'s two
  endpoints, which currently have none at all.
- `mcp-quadlet-deploy` — Quadlet unit, `.env.example` entries,
  `install-quadlets.sh` wiring, Caddy routes for both `/mcp` and
  `/mcp/`, `--proxy-headers`, and an explicit documented
  `transport_security` decision.
- `mcp-repo-hygiene` — Add the two `.github/dependabot.yml` entries
  (`pip` + `docker`) the new service directory needs, since neither
  ecosystem recurses, and add its section to the hand-maintained SBOM
  in `README.md`.
- `mcp-tests` — Mocked unit tests plus a real `run_integration.sh`
  exercising every tool against a live `api` + Postgres.
- `mcp-docs` — README section on pointing an MCP client at the server,
  the targeted spec revision (`2026-07-28`), and a `docs/plan.md`
  progress-log entry once built.

Dependencies: `mcp-server-scaffold` blocks every other `mcp-*` item.
`api-change-history-endpoint` blocks `mcp-tool-change-history`;
`api-field-definitions` blocks `mcp-tool-describe-code`.
`mcp-detail-endpoint-rate-limit` and `api-identity-rate-limit` must both
land **before** `mcp-quadlet-deploy` (i.e. before the surface is
internet-reachable). `mcp-tests` and `mcp-docs` come last. The two
`api-*` rate-limit items are independent of everything else and could
land at any time — they are pre-existing gaps that happen to be
sharpened by this feature.

### Testing (once built)

This project's established methodology — mocked unit tests for each
tool's request/response shaping, then a disposable-container
integration run against the real `api` + Postgres exercising every
tool, then live verification on production by pointing a real MCP
client at the deployed endpoint and confirming each tool returns real
data end-to-end, before considering any todo done.

Two verifications specific to this feature, both learned from the SDK
source rather than assumed:

- **Confirm the endpoint answers behind the real hostname**, not just
  from inside the container. The `421`/host-allowlist failure mode is
  invisible except in the server log and would otherwise be discovered
  by a user, not by us.
- **Confirm the `/mcp` → `/mcp/` redirect resolves over HTTPS**, since
  a missing `--proxy-headers` produces a redirect that MCP clients
  deliberately refuse to follow.

## 12b. Swagger / OpenAPI Compatibility — Design (NOT BUILT)

**Status: deferred.** Nothing in this section is implemented. It is a
design record so the work can be picked up later without redoing the
investigation. The findings below were measured against the running
production stack; see the Progress Log entry "Swagger / OpenAPI
compatibility — investigated, documented, not built" for how.

> **Read this first if you are picking the work up.** Two premises here
> are version- and configuration-dependent and must be re-verified before
> any code is written, because if either has changed the design changes
> with it:
>
> 1. **That FastAPI still ignores `openapi_version`.** If a newer release
>    honours it, the entire `swagger-openapi-30-endpoint` todo collapses
>    to a one-line constructor argument.
> 2. **That `web/Caddyfile` still proxies only `/api/*`.** If it gained
>    broader routes, the "the docs are unreachable" premise no longer
>    holds.

### The problem

The API is FastAPI, so an OpenAPI document exists internally. "Swagger
compatible" still is not satisfied, for four independent reasons.

**1. The docs are not reachable at all.** Caddy proxies only `/api/*`,
while FastAPI serves its docs at root paths, so:

| URL | Status | What actually comes back |
|---|---|---|
| `/openapi.json` | **200** | SvelteKit `index.html` |
| `/docs` | **200** | SvelteKit `index.html` |
| `/api/openapi.json` | 404 | — |
| `/api/docs` | 404 | — |

The `200`s are why this went unnoticed. Any check that asserts on status
codes alone reports these as healthy.

**2. The spec is OpenAPI 3.1.0.** Swagger UI 5+ reads it, but Swagger 2.0
tooling, many codegen targets, and gateways such as AWS API Gateway and
Azure APIM do not.

**3. The obvious fix does not work.** `FastAPI(openapi_version="3.0.3")`
is silently ignored on 0.141 — see the warning above.

**4. The document is structurally thin.**

- 18 of 26 `GET` endpoints declare a completely untyped `{}` `200`:
  every detail endpoint, `search`, both `identity` endpoints,
  `field-definitions`, `watches`, `channels`, `auth/me`, `admin/me`,
  `healthz`.
- `Page.items` is `array of {}`, so even the eight "typed" endpoints stop
  at the pagination wrapper.
- No `securitySchemes`, despite cookie-based user *and* admin sessions
  (`api/app/deps.py` reads `settings.session_cookie_name` and
  `settings.admin_session_cookie_name`).
- Only `200`/`422` documented; the real `401`, `403`, `404` and `429`
  appear nowhere.
- `info.description` empty; no `servers`, contact, licence, or top-level
  `tags` metadata.
- Auto-derived summaries are poor ("By Frn", "Detail", "Healthz") and
  operationIds are codegen-hostile (`search_api_search_get`).

### Scope decided with the user

- Keep 3.1 as the primary spec **and additionally publish 3.0.3**.
- Docs public, but **`/api/admin/*` hidden** from the published document.
- **Full** quality: response models everywhere, error responses, security
  schemes, descriptions, examples.
- **"Try it out" enabled** against production.

### Design

#### Routing — fix by moving the doc URLs, not by editing Caddy

```python
app = FastAPI(
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    ...
)
```

This needs **no Caddyfile change**, which is the point. It keeps all API
surface under one prefix, inherits the existing `/api/*` proxy and the
global security-header block, cannot collide with a future SPA route
named `/docs`, and leaves alone the one file that has previously taken
the whole `web` container down when it was wrong.

Swagger UI then fetches `/api/openapi.json` same-origin, so **no CORS
entry is needed**. Use `servers: [{"url": "/"}]` — a *relative* server URL
deliberately, so "Try it out" targets whatever host is serving the page.
Hardcoding `PUBLIC_BASE_URL` would make a dev instance's "Try it out"
silently fire requests at production.

#### Hiding admin, with a reversible toggle

Drive `include_in_schema` on the admin router from a new
`FCCULS_OPENAPI_INCLUDE_ADMIN` setting, default `false`. Documentation
only — the routes stay functional either way. A setting rather than a
hardcoded `False` because an internal instance may legitimately want the
admin surface documented, and flipping `.env` is cheaper than a code
change plus rebuild. Note this is not a security control; admin is
password-gated and obscurity was never the mechanism.

#### Response models — generated from the schema, not hand-transcribed

This is the largest and most failure-prone part. Detail endpoints
`SELECT *` against wide FCC tables (`amat_hd` alone has 59 columns;
there are 29 `CREATE TABLE` statements). Hand-writing Pydantic models for
those would duplicate the entire database schema in Python and guarantee
silent drift.

This project already solved exactly this problem: `scripts/gen_field_defs.py`
generates `api/app/field_defs.py` from a single source and ships a
`--check` drift gate, precisely because hand-transcription drifts. Follow
that precedent:

- **New `scripts/gen_row_models.py`** parses the `CREATE TABLE IF NOT
  EXISTS` blocks in `db/*.sql` — which are explicitly typed (`BIGINT`,
  `TEXT`, `DATE`, `BOOLEAN`, `TIMESTAMPTZ`, `NUMERIC`) — and emits
  `api/app/row_models.py`, one model per table with every column optional,
  since a `LEFT JOIN` or absent section legitimately yields nulls.
- **`--check` mode** wired into the API test run so staleness fails the
  build.
- The migrations are the right source of truth: they are literally what
  `SELECT *` returns.

**Hand-written envelope models** then compose those generated row models.
These are hand-written on purpose — they are an API design decision, not
a reflection of the schema:

| Endpoint | Envelope |
|---|---|
| `/api/amateur/{call_sign}` | `header`, `entity`, `amateur_specific`, `history[]`, `change_log[]`, `related_identities[]` |
| `/api/towers/{registration_number}` | `registration`, `entities[]`, `coordinates[]`, `history[]`, `change_log[]`, `related_by_site[]`, `related_by_frn[]` |
| `/api/gmrs\|aircraft\|ship/{call_sign}` | built from `personal_services.py`'s `SERVICE_CONFIGS`/`DetailSection` list, so the models stay generated from the same config the routes are |
| `/api/search` | `query`, `results[]` of `{result_type, key, label, unique_system_identifier, score}` |
| `/api/identity/frn/{frn}` | `frn`, `members[]` of `{source, subject_key, entity_name, licensee_id}` |
| `/api/identity/address` | `address_key`, `members[]` |
| `/api/history`, `/api/new-hams` | typed `items[]` on the existing `Page`/`NewHamsPage` |
| `watches`, `channels`, `auth/me`, `healthz` | small hand-written models |

Two details worth getting right rather than discovering late:

- Make `Page` generic. `Page[AmateurRow]` gives each browse endpoint a
  distinct component schema instead of one shared untyped `Page`.
- Amateur history rows carry a `code_description` field that is **not** a
  database column — `amateur.py` injects it from `describe_history_code`.
  A naive "the model is just the table" assumption drops it.

#### Error responses and security schemes

- A shared `responses={...}` mapping applied per-router for the codes each
  router *actually* raises — `429` on rate-limited public reads, `404` on
  detail lookups, `401`/`403` on authenticated routes — rather than a
  blanket copy-paste onto every operation.
- `securitySchemes` declaring two `apiKey`-in-`cookie` schemes named from
  `settings.session_cookie_name` and `settings.admin_session_cookie_name`,
  applied only to routes that require them.

#### The 3.0.3 document

New `GET /api/openapi-3.0.json` returning a transformed copy:

- Recursively rewrite `anyOf: [X, {"type":"null"}]` → `X` +
  `nullable: true`.
- **For a `$ref` variant the `$ref` must be wrapped in `allOf`**, because
  in 3.0 a sibling key alongside `$ref` is ignored. The current spec has
  no nullable `$ref` — but adding response models *creates* them, so this
  case must be handled before it appears, not after it silently produces
  a wrong spec.
- Cache the result alongside FastAPI's own `app.openapi()` cache rather
  than recomputing per request.
- Swagger UI keeps pointing at the 3.1 document; the 3.0 one is for
  external tooling and is linked from the docs description.

### Testing (when this is built)

Real tests in disposable containers, then live verification, per this
project's methodology:

- **New `api/tests/test_openapi.py`**: every operation has a non-empty
  summary and description; no auto-generated `_api_..._get` operationIds
  and all are unique; **no `200` response has an empty schema** — the
  regression gate for the biggest gap, which would fail for 18 endpoints
  today; `/api/admin/*` absent by default and present when the setting is
  enabled; `securitySchemes` exist and are referenced; the downgraded
  document contains no `"type": "null"` and its `paths`/`components`
  counts match the 3.1 document exactly, so nothing is silently dropped.
- **Independent validation** with `openapi-spec-validator` as a test
  dependency, asserting the 3.1 document validates as 3.1 **and** the
  downgraded one validates as 3.0. This is the acceptance criterion for
  the 3.0 deliverable. The prototype confirmed the transform leaves no
  residual 3.1 constructs, but that is a weaker claim than a real
  validator accepting it, and the gap must be closed rather than assumed
  away.
- **`scripts/gen_row_models.py --check`** in the API test script.
- **Live verification**: `/api/docs` and `/api/redoc` return real
  Swagger/ReDoc HTML — asserting on **body content, not status codes**,
  since the SPA fallback returning `200` is exactly what made this look
  healthy while being broken; both spec URLs report the right `openapi`
  version; a real "Try it out" call against `/api/search` succeeds from
  the browser; `/api/admin/*` is absent from the published document.

### Files this would touch

- `api/app/main.py` — doc URLs, metadata, `servers`, tag metadata, custom
  `generate_unique_id_function`, the 3.0 endpoint.
- `api/app/config.py` — `openapi_include_admin`.
- `api/app/openapi_compat.py` *(new)* — the downgrade transform.
- `api/app/row_models.py` *(new, generated)*, `api/app/schemas.py` *(new)*.
- `api/app/pagination.py` — make `Page` generic.
- `api/app/routers/*.py` — `response_model`, summaries, docstrings,
  `responses`, security; `admin.py` gets the schema toggle.
- `scripts/gen_row_models.py` *(new)*.
- `api/tests/test_openapi.py` *(new)*, `api/tests/run_integration.sh`,
  `api/requirements.txt` (test-only validator dependency).
- `.env.example`, `README.md`, `docs/architecture.md`, `docs/plan.md`.
- **No `web/Caddyfile` change** — deliberately.

Rebuild scope when built: the **`api`** image only. `web` is untouched.

### Todos (all `blocked` until this is greenlit)

- `swagger-docs-routing` — Move `docs_url`/`redoc_url`/`openapi_url` under
  `/api/`, add `servers`, confirm reachability by asserting on body
  content rather than status code.
- `swagger-app-metadata` — `info.description`, contact/licence, top-level
  tag descriptions sourced from the existing router module docstrings,
  clean `operationId` generation, real summaries per route.
- `swagger-admin-hiding` — `FCCULS_OPENAPI_INCLUDE_ADMIN` (default off)
  driving `include_in_schema` on the admin router.
- `swagger-security-schemes` — Cookie `securitySchemes` for user and admin
  sessions, applied to the routes that need them.
- `swagger-error-responses` — Document the real `401`/`403`/`404`/`429`
  responses per router.
- `swagger-row-models-generator` — `scripts/gen_row_models.py` deriving
  `api/app/row_models.py` from `db/*.sql`, with a `--check` drift gate.
- `swagger-response-models` — Generic `Page[T]` plus hand-written envelope
  models; `response_model` on every endpoint, including the non-column
  `code_description` field.
- `swagger-openapi-30-endpoint` — `api/app/openapi_compat.py` +
  `GET /api/openapi-3.0.json`, handling the `$ref`-in-`allOf` nullable
  case.
- `swagger-tests` — `api/tests/test_openapi.py` plus
  `openapi-spec-validator` asserting both documents validate.
- `swagger-docs-update` — README/architecture updates and a Progress Log
  entry, once the feature actually ships.

Dependencies: `swagger-response-models` depends on
`swagger-row-models-generator`; `swagger-openapi-30-endpoint` depends on
`swagger-response-models` (the `$ref` nullable case only appears once
response models exist); `swagger-tests` depends on all of the above;
`swagger-docs-update` comes last. The remaining five are mutually
independent.

### Notes

- Enabling "Try it out" publicly makes `POST /api/auth/request-link`
  callable from the docs UI. It is already rate-limited (5/hour per
  email+IP) and already callable by any HTTP client, so this changes
  convenience, not exposure — stated explicitly rather than left implied.
- The generated row models describe **raw FCC columns**. They are not the
  decoded, tooltipped values the frontend and MCP server present;
  `describe_code` remains the way to interpret codes, and the OpenAPI
  descriptions should say so rather than implying the raw values are
  self-explanatory.
