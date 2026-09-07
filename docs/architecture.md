# Architecture: Data Flow & Operational Logic

Visual companion to `README.md` (deployment/configuration) and
`docs/user-guide.md` (end-user features). This file documents **how the
system actually works** — what moves data where, and what decisions each
component makes.

Diagrams are [Mermaid](https://mermaid.js.org/), which GitHub renders
natively in Markdown — no build step, no generated image assets to keep in
sync with the source. Edit the code blocks directly.

## Contents

- [1. System topology](#1-system-topology) — containers, networks, volumes
- [2. Level-0 data flow](#2-level-0-data-flow) — FCC to end user
- [3. Ingestion: daily catch-up logic](#3-ingestion-daily-catch-up-logic)
- [4. Ingestion: per-row decision logic](#4-ingestion-per-row-decision-logic)
- [5. Notification pipeline](#5-notification-pipeline)
- [6. Delivery lifecycle](#6-delivery-lifecycle) — retry/failure states
- [7. Passwordless authentication](#7-passwordless-authentication)
- [8. Test-send](#8-test-send)
- [9. Read-request lifecycle](#9-read-request-lifecycle)
- [10. Data model](#10-data-model)
- [11. Deployment: update.sh](#11-deployment-updatesh)
- [12. Operational runbook](#12-operational-runbook) — install & recovery

---

## 1. System topology

Nine containers on one rootless Podman host, on a single internal network
(`fcculs`). **Only `web` publishes a host port** — everything else is
reachable only from inside the network, by container DNS name.

```mermaid
flowchart TB
    subgraph outside["Outside world"]
        user["Browser"]
        fcc["data.fcc.gov<br/>ULS public files"]
        smtp["SMTP relay"]
        hooks["ntfy / Discord / Telegram<br/>Matrix / generic webhook"]
    end

    cf["Cloudflare Tunnel<br/>(cloudflared, host-managed)"]

    subgraph host["Podman host (rootless)"]
        subgraph net["network: fcculs"]
            web["<b>web</b><br/>Caddy + SvelteKit static build<br/>:8080 (published)"]
            api["<b>api</b><br/>FastAPI + uvicorn<br/>:8000"]
            ingestor["<b>ingestor</b><br/>APScheduler daily job"]
            dispatch["<b>notifier-dispatch</b><br/>match loop"]
            worker["<b>notifier-worker</b><br/>RQ consumer"]
            pg[("<b>postgres</b><br/>:5432")]
            redis[("<b>redis</b><br/>:6379")]
        end

        subgraph oneshot["Oneshot units (not long-running)"]
            migrate["<b>migrate</b><br/>db/*.sql on boot"]
            bootstrap["<b>bootstrap</b><br/>manual full load"]
        end

        pgvol[("pgdata volume")]
    end

    user --> cf --> web
    web -->|"/api/*"| api
    web -->|"everything else:<br/>static SPA"| web

    api --> pg
    api --> redis
    ingestor --> pg
    dispatch --> pg
    dispatch -->|"enqueue"| redis
    worker -->|"consume"| redis
    worker --> pg

    fcc -->|"HTTPS download"| ingestor
    fcc -->|"HTTPS download"| bootstrap
    api -->|"magic-link mail"| smtp
    worker -->|"deliver alerts"| smtp
    worker -->|"deliver alerts"| hooks

    migrate --> pg
    bootstrap --> pg
    pg --- pgvol
```

**Why the notifier is two containers.** Matching (DB-only, fast, must not
block) is deliberately separated from sending (network-bound, slow,
needs retries). `dispatch` loops on `DISPATCH_INTERVAL_SECONDS`; one or
more `worker` processes drain the queue independently. Neither can stall
the other.

---

## 2. Level-0 data flow

The two independent paths through the system: **ingest** (scheduled,
write) and **serve** (on-demand, read), joined only by Postgres.

```mermaid
flowchart LR
    fcc[/"FCC ULS<br/>weekly dumps +<br/>daily transaction files"/]

    subgraph ingestpath["Ingest path — scheduled, writes"]
        dl["download<br/>+ unzip"]
        parse["parse<br/>pipe-delimited .dat"]
        diff["diff vs<br/>current DB row"]
        upsert["upsert"]
        events["emit<br/>change_events"]
    end

    db[("PostgreSQL")]

    subgraph servepath["Serve path — on-demand, reads"]
        rest["REST API"]
        spa["SvelteKit SPA"]
    end

    subgraph alertpath["Alert path — event-driven"]
        match["match events<br/>against watches"]
        send["render + deliver"]
    end

    fcc --> dl --> parse --> diff
    diff --> upsert --> db
    diff --> events --> db

    db --> rest --> spa --> enduser["End user<br/>(browser)"]
    db --> match --> send --> enduser2["End user<br/>(email/SMS/webhook)"]

    style ingestpath fill:#1f2933,stroke:#3e4c59
    style servepath fill:#1f2933,stroke:#3e4c59
    style alertpath fill:#1f2933,stroke:#3e4c59
```

`change_events` is the pivot: it is simultaneously the user-visible
"Change History" on detail pages **and** the trigger source for all
alerting. Nothing else feeds alerts.

---

## 3. Ingestion: daily catch-up logic

The most subtle logic in the system. **FCC daily files are named by
weekday only** (`l_am_mon.zip`), are **overwritten in place on a 7-day
rotation**, and each is published **~05:00–13:00 UTC the day *after* the
weekday it is named for**.

So the naive approach — derive today's filename from today's weekday —
fetches a file that has not been refreshed yet and therefore still holds
**the same weekday from the previous week**. That was a real bug in this
project; see `docs/plan.md`'s Progress Log.

The scheduler instead treats filenames as opaque and derives the true
date from each file's `Last-Modified` header.

```mermaid
flowchart TD
    start(["Daily cron fires<br/>(default 13:30 UTC)"]) --> svc{"For each service:<br/>amateur, tower"}

    svc --> head["HEAD all 7 weekday files"]
    head --> resolve["Resolve each file's real data date:<br/>walk back from Last-Modified to the<br/>first matching weekday"]

    resolve --> undated{"Date<br/>resolvable?"}
    undated -->|"no — missing or<br/>unparseable header"| skipfile["Log warning, skip file<br/>(never guess)"]
    undated -->|"yes"| known

    known["Query ingest_runs for<br/>dates already loaded"] --> pending["pending = available<br/>− already ingested<br/>− outside 7-day window"]

    pending --> any{"Any<br/>pending?"}
    any -->|"no"| nothing["Log 'nothing to do'<br/>— no download at all"]
    any -->|"yes"| loop["For each pending date,<br/><b>oldest first</b>"]

    loop --> dlday["Download + extract<br/>into its own temp dir"]
    dlday --> ingestday["ingest_file per .dat member<br/><b>effective_date = real data date</b>,<br/>not the run date"]
    ingestday --> record["INSERT ingest_runs<br/>(service, data_date, sha256, counts)"]
    record --> more{"More<br/>pending?"}
    more -->|"yes"| loop
    more -->|"no"| done

    skipfile --> known
    nothing --> done
    done{"Anything<br/>ingested?"} -->|"yes"| refresh["REFRESH MATERIALIZED VIEW<br/>identity_by_frn, towers_by_site,<br/>entities_by_address"]
    done -->|"no"| skiprefresh["Skip refresh<br/>(nothing changed)"]

    refresh --> fin(["Run complete"])
    skiprefresh --> fin
```

**Properties this buys us:**

| Property | Mechanism |
|---|---|
| **Self-healing** | A missed run is picked up automatically next time, as long as the day is still inside FCC's rolling 7-day window. |
| **Idempotent** | `ingest_runs` has `UNIQUE (service, data_date)`; an already-loaded day is skipped *without downloading*. Row-level upserts mean even a forced re-ingest cannot double-count. |
| **Correctly dated** | `effective_date` comes from the file's resolved date, so change history and the New Hams feed line up with reality. |
| **Partial-failure safe** | Each day gets its own temp dir and its own `ingest_runs` row, so a failure mid-catch-up keeps every earlier day recorded. |
| **Ordered** | Oldest-first means multi-day catch-ups apply chronologically, so diffs are computed against the correct prior state. |

> **Hard limit:** FCC keeps only 7 rotating files. A gap longer than that
> is **unrecoverable from the daily feed** — it needs a fresh
> `--bootstrap`. See [§12](#12-operational-runbook).

---

## 4. Ingestion: per-row decision logic

What happens to a single parsed record. The `generate_diffs` flag is the
top-level fork: bootstrap loads take a batched fast path that emits **no**
change events (otherwise a fresh install would fire hundreds of thousands
of bogus "new license" alerts).

```mermaid
flowchart TD
    row(["One parsed .dat record"]) --> mode{"generate_diffs?"}

    mode -->|"false<br/>(bootstrap / full dump)"| batch["Batched upsert<br/>(executemany)<br/><b>no change_events</b>"]
    batch --> nextrow(["Next record"])

    mode -->|"true<br/>(daily incremental)"| lookup["SELECT current row<br/>by natural key"]
    lookup --> exists{"Row already<br/>in DB?"}

    exists -->|"yes"| diff["diff_rows(existing, new)"]
    diff --> haschanges{"Any fields<br/>differ?"}
    haschanges -->|"no"| upsert
    haschanges -->|"yes"| fieldevents["INSERT one change_event<br/>per changed field<br/>(old → new)"]
    fieldevents --> upsert

    exists -->|"no — brand new"| hasfrn{"Table carries an FRN<br/>(amat_en / tower_en)<br/>and FRN is non-blank?"}
    hasfrn -->|"no"| upsert
    hasfrn -->|"yes"| amateur{"Table is<br/>amat_en?"}

    amateur -->|"no (tower_en)"| synth["INSERT synthetic change_event<br/>field_name = tower_registered<br/>is_new_operator = false"]
    amateur -->|"yes"| prior{"Does this FRN already have<br/>ANY amateur license?<br/>(checked BEFORE this upsert)"}

    prior -->|"yes — existing ham<br/>getting another callsign"| synth2["INSERT synthetic change_event<br/>field_name = license_granted<br/><b>is_new_operator = false</b>"]
    prior -->|"no — first ever"| synth3["INSERT synthetic change_event<br/>field_name = license_granted<br/><b>is_new_operator = true</b><br/>🎉 New Ham"]

    synth --> upsert
    synth2 --> upsert
    synth3 --> upsert
    upsert["upsert_row()"] --> nextrow
```

**Two non-obvious rules encoded here:**

1. **Brand-new rows produce no field-level diffs.** `diff_rows()` returns
   nothing when there is no prior row — otherwise every field would read
   as "changed from nothing." But that would leave a new licensee's first
   grant firing *no event at all*, so a single **synthetic** event is
   emitted instead. This is what makes "watch by FRN before you have a
   callsign" work.
2. **`is_new_operator` is computed once, at ingest, and never revisited.**
   It is checked *before* the row's own upsert, so the record cannot see
   itself. Storing it durably (rather than deriving it live) means it can
   never retroactively flip when that person later earns a second/vanity
   callsign — the celebration is a permanent historical fact.

---

## 5. Notification pipeline

From a stored `change_event` to a message in someone's inbox. Matching and
sending are separate processes joined by a Redis queue.

```mermaid
sequenceDiagram
    autonumber
    participant I as ingestor
    participant DB as PostgreSQL
    participant D as notifier-dispatch
    participant R as Redis (RQ)
    participant W as notifier-worker
    participant X as SMTP / webhook

    I->>DB: INSERT change_events
    Note over D: loops every<br/>DISPATCH_INTERVAL_SECONDS

    D->>DB: Match events to active watches<br/>(callsign / uls_id / asr_reg / frn)<br/>LEFT JOIN to exclude pairs<br/>already delivered
    DB-->>D: new (watch, event) pairs

    D->>DB: INSERT notification_deliveries (pending)<br/>ON CONFLICT DO NOTHING
    DB-->>D: ids actually created

    loop per new delivery
        D->>R: enqueue send_delivery(id)<br/>retry max=3, backoff 30s/120s/600s
    end

    W->>R: dequeue job
    W->>DB: Load delivery + watch<br/>+ channel + change_event
    W->>W: render_message()
    W->>X: send via channel_type

    alt delivered
        X-->>W: success
        W->>DB: status = sent, sent_at = now()
    else send failed
        X-->>W: SendError
        W->>DB: attempts += 1, last_error = ...<br/>status = failed if attempts >= max,<br/>else stays pending for retry
    end
```

**Double idempotency guard.** Matching excludes pairs that already have a
delivery row (`LEFT JOIN ... WHERE nd.id IS NULL`), *and* the insert uses
`ON CONFLICT DO NOTHING` against a unique constraint on
`(watch_id, change_event_id)`. Only ids actually returned by `RETURNING`
get enqueued — so two dispatch runs racing each other cannot double-send.

---

## 6. Delivery lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: matcher records<br/>(watch, event) pair
    pending --> sent: sender succeeds
    pending --> pending: send failed and<br/>attempts < MAX_DELIVERY_ATTEMPTS<br/>(RQ retries with backoff)
    pending --> failed: send failed and<br/>attempts >= MAX_DELIVERY_ATTEMPTS
    sent --> [*]
    failed --> [*]

    note right of pending
        attempts increments on every try.
        last_error always records the most
        recent failure reason, even while
        still retrying.
    end note
```

Unknown `channel_type`, or a channel deleted mid-flight, fails the
delivery immediately with a recorded reason rather than retrying — there
is nothing a retry could fix.

---

## 7. Passwordless authentication

No passwords are stored or transmitted. A single-use, hashed, expiring
token is emailed; possession of the mailbox is the proof of identity.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant W as web (Caddy/SPA)
    participant A as api
    participant DB as PostgreSQL
    participant RL as Redis
    participant M as SMTP relay

    U->>W: Enter email, submit
    W->>A: POST /api/auth/request-link
    A->>RL: enforce_rate_limit<br/>(per email + IP)

    alt over limit
        A-->>U: 429 Too Many Requests
    else allowed
        A->>DB: SELECT user, INSERT if absent
        A->>A: generate token<br/>store only SHA-256 hash
        A->>DB: INSERT magic_link_tokens<br/>(hash, expires_at)
        A->>M: email link with RAW token (never stored)
        A-->>U: 202 "If that email is valid..."<br/>(generic — never leaks<br/>whether the account exists)
    end

    U->>W: Click emailed link
    W->>A: GET /api/auth/verify?token=...
    A->>DB: look up by hash

    alt not found / already consumed / expired
        A-->>U: 400 Invalid token
    else valid
        A->>DB: mark consumed_at
        A-->>U: Set-Cookie: signed session<br/>HttpOnly, SameSite=Lax,<br/>Secure if resolved origin is https
    end
```

**Host-header hardening.** The base URL used in the emailed link and the
cookie's `Secure` decision is derived from `X-Forwarded-Host`/
`X-Forwarded-Proto` (so the app works behind any tunnel hostname without
config drift) — **but only if the resolved origin is in the operator's
`CORS_ALLOW_ORIGINS` allow-list.** Otherwise it falls back to the static
configured base URL. Without that check, an attacker could supply a
crafted `Host` header and have it echoed into a real user's magic-link
email.

---

## 8. Test-send

Lets a user prove a channel works before relying on it. Notable because
the `api` and `notifier` are **separate containers with separate
codebases** — the job is referenced across that boundary by *string path*,
not an imported function.

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant A as api
    participant R as Redis (RQ)
    participant W as notifier-worker
    participant X as Channel target
    participant DB as PostgreSQL

    U->>A: POST /api/channels/{id}/test
    A->>DB: verify caller owns channel
    A->>A: rate-limit per user
    A->>R: enqueue "app.jobs.send_test_message"<br/>(by string path)

    W->>R: dequeue
    W->>DB: load channel config
    W->>W: render_test_message()<br/>truncated to the channel's<br/>practical length limit
    W->>X: send

    alt success
        X-->>W: ok
        W->>DB: is_verified = true
    end

    loop api polls the job
        A->>R: job status?
    end

    alt finished in time
        A-->>U: {"status": "sent"}
    else still running
        A-->>U: {"status": "timeout"}
        Note over W,DB: worker still sets is_verified<br/>when the slow send lands —<br/>the DB is the source of truth,<br/>the poll is only a fast path
    end
```

A real ntfy.sh POST was observed taking ~11s during live testing, longer
than the API's poll window — hence the worker, not the API, owns the
`is_verified` write.

---

## 9. Read-request lifecycle

Every public page load. Caddy is the only entry point; it splits static
assets from API calls.

```mermaid
flowchart TD
    req(["Browser request"]) --> caddy["Caddy :8080"]
    caddy --> hdr["Add security headers:<br/>HSTS, nosniff, Referrer-Policy,<br/>X-Frame-Options, frame-ancestors"]
    hdr --> route{"Path starts<br/>with /api/ ?"}

    route -->|"no"| static["Serve SvelteKit build from /srv<br/>try_files → index.html<br/>(client-side routing)"]
    static --> spa["SPA boots, then fetches<br/>the data it needs from /api/*"]
    spa --> route

    route -->|"yes"| proxy["reverse_proxy api:8000"]
    proxy --> cors{"CORS origin<br/>allowed?"}
    cors -->|"no"| reject["Blocked by browser<br/>(no ACAO header returned)"]
    cors -->|"yes"| limited{"Rate-limited<br/>endpoint?"}

    limited -->|"yes: search, browse,<br/>new-hams, auth, admin"| rl["Check Redis counter"]
    rl --> over{"Over<br/>limit?"}
    over -->|"yes"| r429["429 Too Many Requests"]
    over -->|"no"| authck
    limited -->|"no"| authck

    authck{"Endpoint requires<br/>a session?"}
    authck -->|"yes"| cookie["Verify signed session cookie"]
    cookie --> valid{"Valid?"}
    valid -->|"no"| r401["401 Unauthorized"]
    valid -->|"yes"| query
    authck -->|"no — public read"| query

    query["Query Postgres<br/>via async pool"] --> resp["JSON response"]
```

---

## 10. Data model

Three groups: **FCC raw tables** (mirror the public files), **application
tables** (users, watches, delivery), and **derived objects** (materialized
views for identity grouping). `change_events` is the bridge between the
FCC side and the application side.

```mermaid
erDiagram
    amat_hd ||--o{ amat_hs : "history of"
    amat_hd ||--|| amat_en : "entity for"
    amat_hd ||--|| amat_am : "amateur detail for"
    tower_ra ||--|| tower_en : "owner of"
    tower_ra ||--o{ tower_co : "antenna coords"
    tower_ra ||--o{ tower_hs : "history of"

    amat_en ||--o{ change_events : "generates"
    tower_en ||--o{ change_events : "generates"

    users ||--o{ notification_channels : owns
    users ||--o{ watches : owns
    users ||--o{ magic_link_tokens : "signs in with"
    notification_channels ||--o{ watches : "notifies via"

    watches ||--o{ notification_deliveries : "triggers"
    change_events ||--o{ notification_deliveries : "triggers"

    ingest_runs {
        text service
        date data_date "UNIQUE with service"
        text source_file
        timestamptz last_modified
        text content_sha256
        int rows_ingested
        int changes_recorded
        text status
    }

    change_events {
        text subject_type
        text subject_key "callsign or ASR reg no"
        text uls_system_id
        text frn "enables FRN watches"
        text field_name
        text old_value
        text new_value
        date effective_date "real FCC data date"
        bool is_new_operator "New Hams flag"
    }

    watches {
        int user_id
        text subject_type "callsign|uls_id|frn|asr_registration_number"
        text subject_value
        int channel_id
        bool is_active
    }

    notification_deliveries {
        int watch_id "UNIQUE with change_event_id"
        int change_event_id
        text status "pending|sent|failed"
        int attempts
        text last_error
    }
```

Materialized views (refreshed at the end of any ingest that wrote data):

| View | Groups by | Powers |
|---|---|---|
| `identity_by_frn` | FRN | "all licenses and towers for this identity" |
| `towers_by_site` | rounded lat/lon | "other structures at this site" |
| `entities_by_address` | normalized mailing address | "related licensees" |

---

## 11. Deployment: update.sh

```mermaid
flowchart TD
    start(["bash deploy/update.sh"]) --> pull{"--no-pull?"}
    pull -->|"no"| git["git pull origin master"]
    pull -->|"yes"| rev
    git --> rev["rev = current commit SHA"]

    rev --> force{"--force?"}
    force -->|"yes"| build
    force -->|"no"| check["Read org.opencontainers.image.revision<br/>label from <b>all four</b> images:<br/>api, ingestor, notifier, web"]

    check --> allmatch{"Every image<br/>labelled with rev?"}
    allmatch -->|"yes"| skip(["Already up to date.<br/>Nothing to do."])
    allmatch -->|"no — even one stale<br/>or never built"| build

    build["Build each image,<br/>labelled with rev"] --> webnote["<b>web</b> also needs<br/>--build-context docs=./docs<br/>for the in-app /help page"]
    webnote --> tag["Tag :latest and :short-sha"]
    tag --> restart{"--no-restart?"}
    restart -->|"yes"| doneb(["Images built,<br/>units untouched"])
    restart -->|"no"| units["systemctl --user restart<br/>each service unit"]
    units --> verify(["Verify: curl / and /api/healthz"])
```

**Why all four labels are checked.** Images build sequentially, so a
failure partway through can leave `api` correctly labelled while `web` is
stale. Checking only `api` (the original behaviour) made a retry report
"Already up to date" and leave a never-successfully-built image in place
indefinitely. See `docs/plan.md`'s Progress Log.

---

## 12. Operational runbook

### Fresh install

```mermaid
flowchart TD
    a(["New host"]) --> b["Configure .env<br/>(SESSION_SECRET is mandatory —<br/>the api refuses to start on the default)"]
    b --> c["deploy/install-quadlets.sh"]
    c --> d["migrate unit applies db/*.sql"]
    d --> e["Start fcculs-bootstrap.service<br/>full weekly dumps, no change_events"]
    e --> f["scheduler.py --catch-up<br/><b>required, not optional</b>"]
    f --> g["scheduler.py --status<br/>confirm no [MISSING] days"]
    g --> h(["Daily cron takes over"])
```

> The weekly dump is cut once a week, so on any day but publication day it
> is **already 1–6 days stale on arrival**. Skipping the `--catch-up` step
> is the single most likely way a new instance silently starts life with a
> data gap and an empty New Hams feed.

### Diagnosing a suspected gap

```mermaid
flowchart TD
    sym(["Data looks stale, or the New Hams<br/>feed has a visibly missing day"]) --> status["podman exec ingestor<br/>python scheduler.py --status"]
    status --> missing{"Any days<br/>marked [MISSING]?"}

    missing -->|"no"| upstream["Ingestion is healthy.<br/>FCC may simply have published<br/>nothing that day — weekends and<br/>holidays produce empty archives."]
    missing -->|"yes"| age{"Missing days still<br/>inside the rolling<br/>7-day window?"}

    age -->|"yes"| catchup["scheduler.py --catch-up<br/>(safe to run anytime;<br/>already-loaded days are skipped)"]
    catchup --> recheck["--status again to confirm"]

    age -->|"no — gap > 7 days"| gone["Those days are <b>gone upstream</b>.<br/>FCC keeps only 7 rotating files."]
    gone --> reboot["Re-run --bootstrap<br/>(reloads the current complete dump)<br/>then --catch-up"]
    reboot --> caveat["Note: bootstrap emits no change_events,<br/>so alerts and New Hams entries for the<br/>lost window cannot be reconstructed —<br/>the license data itself is fully restored."]
```

### Backup and restore

```mermaid
flowchart LR
    subgraph daily["Daily, via fcculs-backup.timer"]
        b1["deploy/backup.sh"] --> b2["podman exec postgres pg_dump"]
        b2 --> b3["gzip to timestamped file"]
        b3 --> b4["prune dumps older than<br/>retention period"]
    end

    subgraph restore["Manual"]
        r1["deploy/restore.sh dump.gz"] --> r2{"--confirm<br/>passed?"}
        r2 -->|"no"| r3["Refuse<br/>(guards against restoring<br/>over production by accident)"]
        r2 -->|"yes"| r4["Restore into target DB"]
    end
```

Ingested FCC data is always re-downloadable. **User accounts, watches, and
notification-channel configs are not** — they exist only in Postgres,
which is what the backup protects.
