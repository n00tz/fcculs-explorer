-- Operations heartbeats.
--
-- Motivated by a false-alarm investigation: because ingest_runs only gets a
-- new row when there is actually something to ingest, a genuinely quiet FCC
-- publishing period (e.g. a weekend with empty daily files) and a silently
-- dead poller loop looked identical from the database alone. That ambiguity
-- forced a from-scratch log/DB investigation to rule out a real failure.
--
-- This table is a generic, reusable heartbeat: any polling/dispatch loop can
-- upsert its own row into it on *every* cycle, regardless of outcome
-- (including "nothing to do" and backoff cycles). Staleness of the row then
-- proves the loop itself stopped running -- a distinct and more urgent
-- condition than "found nothing new."

CREATE TABLE IF NOT EXISTS service_heartbeats (
    service      TEXT PRIMARY KEY,   -- e.g. 'ingestor-poll', 'notifier-dispatch'
    last_run_at  TIMESTAMPTZ NOT NULL,
    detail       JSONB,              -- small free-form status blob, e.g.
                                      -- {"consecutive_failures": 0, "skip_polls_remaining": 0}
                                      -- or {"enqueued": 3}
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE service_heartbeats IS
    'One row per background loop, upserted every cycle regardless of outcome. Staleness alone means the loop stopped running.';
