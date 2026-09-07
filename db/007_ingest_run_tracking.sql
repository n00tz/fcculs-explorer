-- Daily-ingest tracking, so catch-up runs are idempotent and gaps are visible.
--
-- Background: FCC's daily transaction files are named ONLY by weekday
-- (l_am_mon.zip, r_tow_tue.zip, ...) and are rotated in place weekly -- each
-- is overwritten roughly 12:00 UTC the day AFTER the weekday it is named for.
-- The original scheduler fetched "today's weekday" file every morning, which
-- meant it reliably re-ingested data from a WEEK ago (that day's real file
-- not having been published yet), and any day the ingestor didn't run left a
-- permanent hole once FCC rotated that weekday's file.
--
-- This table records, per (service, data_date), which real calendar day's
-- transactions have actually been ingested. The scheduler consults it to skip
-- days already loaded and to catch up any missed days still inside FCC's
-- rolling 7-day daily window -- see ingestor/scheduler.py.
CREATE TABLE IF NOT EXISTS ingest_runs (
    id              BIGSERIAL PRIMARY KEY,
    service         TEXT        NOT NULL,
    day_of_week     TEXT        NOT NULL,
    data_date       DATE        NOT NULL,
    source_file     TEXT        NOT NULL,
    last_modified   TIMESTAMPTZ,
    content_sha256  TEXT,
    rows_ingested   INTEGER     NOT NULL DEFAULT 0,
    changes_recorded INTEGER    NOT NULL DEFAULT 0,
    status          TEXT        NOT NULL DEFAULT 'success',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One successful ingest per service per real calendar date. This is the
    -- dedupe guarantee: re-running the daily job (or a manual catch-up) can
    -- never double-count a day, no matter how many times it is invoked.
    CONSTRAINT ingest_runs_service_data_date_key UNIQUE (service, data_date)
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_data_date
    ON ingest_runs (data_date DESC);

-- The "New Hams" celebration now windows on effective_date (last 10 days)
-- and orders by date then callsign, so the flagged-rows partial index from
-- db/006 (effective_date DESC, detected_at DESC) no longer matches the sort.
-- Index the window/filter column alone; the per-date callsign ordering is a
-- cheap in-memory sort of one day's grants.
CREATE INDEX IF NOT EXISTS idx_change_events_new_operator_date
    ON change_events (effective_date DESC)
    WHERE is_new_operator;
