-- Notifier support: prevent duplicate deliveries for the same
-- (watch, change_event) pair so the matcher can be re-run safely
-- (e.g. after a crash/restart) without double-sending alerts.
ALTER TABLE notification_deliveries
    ADD CONSTRAINT uq_notification_deliveries_watch_event UNIQUE (watch_id, change_event_id);
