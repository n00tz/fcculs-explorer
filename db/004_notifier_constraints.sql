-- Notifier support: prevent duplicate deliveries for the same
-- (watch, change_event) pair so the matcher can be re-run safely
-- (e.g. after a crash/restart) without double-sending alerts.
-- DO blocks make this idempotent (re-runnable on every stack startup).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_notification_deliveries_watch_event'
    ) THEN
        ALTER TABLE notification_deliveries
            ADD CONSTRAINT uq_notification_deliveries_watch_event UNIQUE (watch_id, change_event_id);
    END IF;
END $$;
