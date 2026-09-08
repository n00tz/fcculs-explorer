-- Continuous ingest polling support.
--
-- The ingestor moved from a single daily cron to polling FCC's download
-- directory every ~15 minutes (see ingestor/scheduler.py). Dedupe still
-- rests entirely on ingest_runs' UNIQUE (service, data_date) constraint
-- from 007 -- that is what makes polling safe at any frequency, and it
-- needs no change here.
--
-- This migration adds only the weekly "complete dump" observation table.
-- FCC publishes a full snapshot per service roughly weekly; the poller
-- notices when a new one appears so an operator can decide whether to
-- re-bootstrap. It deliberately does NOT trigger one: a complete dump is
-- ~200 MB per service and reloading it is disruptive enough to stay a
-- human decision.

CREATE TABLE IF NOT EXISTS complete_dumps (
    service       TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    -- Publication time as reported by FCC (Last-Modified, or the directory
    -- listing converted from US Eastern to UTC). Nullable because FCC has
    -- been observed serving files with no usable Last-Modified at all.
    published_at  TIMESTAMPTZ,
    size_bytes    BIGINT,
    observed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE complete_dumps IS
    'Latest weekly complete dump observed per service. Report-only: never auto-bootstrapped.';
