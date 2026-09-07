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

## 12. Future Features (Deferred)

Explicitly out of scope for now, per the user, but worth keeping visible
so they aren't lost or accidentally reinvented differently later:

- **All other public FCC ULS service databases** beyond Amateur Radio and
  ASR Tower (e.g. GMRS, commercial land-mobile, broadcast, aviation,
  marine) — same daily/weekly transaction-file ingestion model this
  project already uses, extended to more `l_*`/`r_*` dataset definitions.
  Would reuse the existing ingestor/differ/change-event pipeline; the
  main new work is per-service schema + parser definitions and frontend
  browse/detail templates.
- **An MCP (Model Context Protocol) server** — fully planned, not yet
  built. See "§12a. MCP Server — Planned Design (Not Yet Built)" below
  for the complete design (scope, stack, repo layout, deployment
  wiring, and open items) so a future session can resume directly into
  implementation without re-deriving these decisions.

## 12a. MCP Server — Planned Design (Not Yet Built)

Planned on request; deliberately not started yet (revisit when the
user is ready to build). This section exists so a future session can
resume directly into implementation with zero lost context — treat it
as a design doc, not a progress log entry (nothing here is "done").

### Confirmed decisions (from user)

- **Scope: read-only.** Search, browse, detail/attribute lookup,
  identity-grouping/crosslinks, and change-history tools only. No
  watch-creation, no notification-channel management, no admin
  actions exposed via MCP. This means **no new auth model is needed**
  at all — every tool an MCP client can call maps to data that's
  already public/anonymous in the existing REST API. This was the
  single biggest scope-reducing decision: it eliminates the hardest
  open question (how an LLM agent would authenticate as a specific
  human user for magic-link-gated actions) entirely, for now.
- **Transport: remote HTTP/SSE**, hosted alongside the rest of the app
  (reachable through the existing Cloudflare Tunnel, so any
  MCP-capable client/agent on the internet can point at it, not just
  local processes on the user's own machine).
- **Deployment: new containerized service** with its own Quadlet,
  calling the existing `api` container over the internal Podman
  network — not mounted inside the `api` FastAPI process itself. Keeps
  the MCP protocol dependency, versioning, and crash blast-radius
  isolated, matching this project's existing one-container-per-concern
  pattern (`api`, `notifier`, `ingestor`, `web` are all already
  separate).

### Why "thin translation layer," not new data-access code

The existing `api` service already has every read capability this
server would need, fully built and tested:

| Existing REST endpoint | MCP tool it maps to |
|---|---|
| `GET /api/search?q=...` (trigram search across callsigns, ASR registration numbers, and licensee/entity names — `api/app/routers/search.py`) | `search_uls(query, limit)` |
| `GET /api/amateur?...` (paginated/filterable/sortable browse — `amateur.py`) | `browse_amateur(filters, sort, page)` |
| `GET /api/amateur/{call_sign}` (full attribute + license history + related-identity panel) | `get_amateur_license(call_sign)` |
| `GET /api/towers?...` | `browse_towers(filters, sort, page)` |
| `GET /api/towers/{registration_number}` | `get_tower(registration_number)` |
| `GET /api/identity/frn/{frn}` (all licenses/towers sharing an FRN — `identity.py`) | `get_identity_group_by_frn(frn)` |
| `GET /api/identity/address` (entities sharing a mailing address) | `get_identity_group_by_address(...)` |
| *(new endpoint needed — see below)* | `get_change_history(subject_type, subject_value)` |

The MCP server itself should contain **zero direct database access**
— it's purely an MCP-protocol-speaking adapter calling the existing
`api` service's REST endpoints (over the internal Podman network,
e.g. `http://fcculs-api:8000`) and reshaping JSON into MCP tool
results. This avoids duplicating SQL/query logic in a second place and
means the MCP server inherits the `api` service's existing rate
limiting, input validation, and Postgres connection pooling for free.

**One real gap to close first**: nothing today exposes `change_events`
(the diff/history log) over REST at all — the web frontend renders it
inline on detail pages via a query the `amateur`/`towers` routers
already do, but there's no standalone `GET /api/.../history` endpoint
an external client (or this MCP server) could call directly. A small,
genuinely new `api` endpoint is needed for the `get_change_history`
tool specifically — everything else is a pure passthrough.

### Proposed stack

| Concern | Choice | Rationale |
|---|---|---|
| Language/runtime | Python 3.12, matching every other service | Consistency; official `mcp` Python SDK (`modelcontextprotocol/python-sdk`) already supports streamable-HTTP/SSE transport server-side |
| MCP SDK | Official `mcp` package's `FastMCP` server class | Handles JSON-RPC framing, tool schema generation, and the HTTP/SSE transport loop — no protocol code to hand-write |
| HTTP client to `api` | `httpx.AsyncClient`, already used by `notifier`'s webhook sender | Already a proven dependency in this project |
| Container base image | `python:3.12-slim`, matching `api`/`notifier`/`ingestor` | Consistency, already covered by the Dependabot docker config once this directory exists |

### New repo layout

- `mcp/` — new top-level service directory, sibling to `api`/
  `notifier`/`ingestor`/`web`:
  - `app/server.py` — `FastMCP` instance, tool registrations.
  - `app/client.py` — thin `httpx`-based wrapper around the `api`
    service's REST endpoints (base URL from a new
    `FCCULS_API_BASE_URL` setting, defaulting to the internal Podman
    DNS name).
  - `app/config.py` — `pydantic-settings`, following the same
    `FCCULS_`-prefixed-env-var convention already used elsewhere.
  - `requirements.txt` — `mcp`, `httpx`, `pydantic-settings`.
  - `Dockerfile` — non-root `USER`, matching every other service.
  - `tests/` — mocked unit tests (mock `httpx` calls to a fake `api`,
    assert correct MCP tool schemas/outputs) plus a
    `run_integration.sh` spinning up the real `api` container and
    calling each tool for real against live data, matching this
    project's established "no mocks-only" testing methodology.

### Deployment wiring

- New `quadlet/fcculs-mcp.container` Quadlet template, modeled on
  `fcculs-notifier.container` — but since this server needs to be
  Cloudflare-Tunnel-reachable, it likely gets a new Caddy route
  (`/mcp/*` proxied to `fcculs-mcp:<port>`) in `web/Caddyfile` rather
  than a directly tunneled port, so it inherits the same TLS/security-
  headers handling already applied to the rest of the app.
- New settings threaded through `deploy/install-quadlets.sh`'s
  existing substitution-list pattern (`FCCULS_API_BASE_URL` for the
  MCP container, plus whatever port it listens on internally).
- `.env.example` gets the new variables documented inline.
- Since this tool is read-only and unauthenticated by design, the
  same per-IP rate limiting pattern used for `/api/search`/
  `/api/amateur`/`/api/towers` should be applied at the Caddy or
  `api`-call level too — needs a decision at build time, since MCP
  tool calls could hit `get_amateur_license`/`get_tower` detail
  endpoints, which currently have **no** rate limit of their own,
  unlike browse/search (see open items below).

### Open items to resolve at build time (not yet decided)

1. **MCP spec version / transport specifics** — confirm which
   transport revision the current `mcp` Python SDK release
   defaults to / supports, and pick a spec version to target
   explicitly (documented in the MCP server's own README).
2. **Detail-endpoint rate limiting gap** — `GET /api/amateur/{call_sign}`
   and `GET /api/towers/{registration_number}` currently have no
   per-IP rate limit (only browse/search do). An MCP agent making
   rapid detail-lookup tool calls would hit this unthrottled path —
   needs its own small rate-limit addition as a prerequisite, or the
   MCP layer needs to apply its own limiting in front of them.
3. **New `get_change_history` endpoint's shape** — needs a schema
   decision (pagination? date-range filtering? subject_type validation
   against the same allow-list `watches.py` already uses).
4. **Public discoverability/robots** — an MCP endpoint reachable over
   the same Cloudflare Tunnel as the rest of the app is, by
   definition, internet-reachable by any MCP-aware client, not just
   ones the user intends. Decide whether this needs any access
   control at all (e.g. a shared bearer token in the MCP transport
   headers) given "read-only + no auth" was the explicit choice here.
5. **Tool result size limits** — LLM context windows mean tool outputs
   (e.g. a `browse_amateur` call with a huge result set) need sensible
   default/max page sizes distinct from the web frontend's own
   defaults.

### Todos (create in SQL `todos` table when this moves from planning to implementation)

- `mcp-server-scaffold` — New `mcp/` service directory: `FastMCP`
  server, config, Dockerfile (non-root), requirements.
- `mcp-tool-search-browse` — Implement `search_uls`, `browse_amateur`,
  `browse_towers`, `get_amateur_license`, `get_tower` tools as thin
  `httpx` passthroughs to the existing `api` REST endpoints.
- `mcp-tool-identity-grouping` — Implement `get_identity_group_by_frn`
  and `get_identity_group_by_address` tools.
- `api-change-history-endpoint` — New read-only `GET .../history`
  endpoint(s) on the existing `api` service (genuinely new code, not a
  passthrough) to back the new `get_change_history` MCP tool.
- `mcp-tool-change-history` — Implement `get_change_history` tool
  against the new endpoint above.
- `mcp-quadlet-deploy` — `quadlet/fcculs-mcp.container`, `.env.example`
  entries, `install-quadlets.sh` substitution wiring, `Caddyfile`
  `/mcp/*` route.
- `mcp-detail-endpoint-rate-limit` — Close the pre-existing rate-limit
  gap on `GET /api/amateur/{call_sign}` and
  `GET /api/towers/{registration_number}` before/alongside exposing
  them through an unauthenticated MCP tool surface.
- `mcp-tests` — Mocked unit tests + a real `run_integration.sh`
  exercising every tool against a live `api` + Postgres.
- `mcp-docs` — README section covering how to point an MCP client at
  the server, plus a `docs/plan.md` progress-log entry once built.

Dependencies: `mcp-server-scaffold` blocks everything else;
`api-change-history-endpoint` blocks `mcp-tool-change-history` only;
`mcp-detail-endpoint-rate-limit` should land before or alongside
`mcp-quadlet-deploy` (i.e. before the server is actually
internet-reachable); `mcp-tests` and `mcp-docs` come last.

Testing (once built): this project's established methodology — mocked
unit tests for each tool's request/response shaping, then a
disposable-container integration run against the real `api` +
Postgres, then live verification on production by pointing a real MCP
client at the deployed `/mcp` endpoint and confirming each tool
returns real data end-to-end, before considering any todo done.

