-- "New hams" celebration support: durably flags a change_events row as the
-- FIRST-EVER amat_en record seen for that FRN (i.e. this person/club never
-- held an amateur license before). Computed once, at ingest time, by the
-- ingestor (see ingestor/db.py's frn_has_prior_amateur_license()) -- NOT a
-- live join -- so a celebration entry never retroactively disappears if that
-- FRN later grows a second/vanity callsign. Reuses the existing synthetic
-- "license_granted" change_events row emitted for brand-new amat_en rows
-- (see db/005_frn_watch_support.sql); this just adds one more column to it.
ALTER TABLE change_events ADD COLUMN IF NOT EXISTS is_new_operator BOOLEAN NOT NULL DEFAULT FALSE;

-- Partial index: only the (small) set of flagged rows need to be fast to
-- scan/sort for the homepage widget and the full /new-hams listing.
CREATE INDEX IF NOT EXISTS idx_change_events_new_operator
    ON change_events (effective_date DESC, detected_at DESC)
    WHERE is_new_operator;
