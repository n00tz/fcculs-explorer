-- Watch-by-FRN support: lets a brand-new licensee (who only knows their
-- FRN, before any callsign/tower registration exists) set a watch that
-- fires the moment a new amateur license or tower registration tied to
-- that FRN appears. Adds an `frn` column to change_events so the matcher
-- can join a `frn`-type watch against it directly (nullable: only
-- populated for the synthetic "brand new record" events the ingestor
-- emits -- see ingestor/ingest.py -- and left NULL for ordinary
-- field-change events, which continue to be matched by callsign/uls_id/
-- asr_registration_number as before).
ALTER TABLE change_events ADD COLUMN IF NOT EXISTS frn TEXT;

CREATE INDEX IF NOT EXISTS idx_change_events_frn ON change_events (frn);
