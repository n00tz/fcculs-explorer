"""The RQ job body: delivers one pending notification_deliveries row and
updates its status. Designed to be idempotent-safe under RQ retries -- a
retry simply re-attempts the same delivery id, incrementing attempts."""
import logging

import psycopg

from .config import settings
from .db import get_connection
from .render import render_message, render_test_message
from .senders import SENDERS
from .senders.base import SendError

logger = logging.getLogger(__name__)

_LOAD_DELIVERY_SQL = """
SELECT
    nd.id AS delivery_id, nd.attempts,
    w.subject_type, w.subject_value,
    c.channel_type, c.config,
    ce.field_name, ce.old_value, ce.new_value, ce.source_file, ce.effective_date, ce.detected_at
FROM notification_deliveries nd
JOIN watches w ON w.id = nd.watch_id
JOIN notification_channels c ON c.id = w.channel_id
JOIN change_events ce ON ce.id = nd.change_event_id
WHERE nd.id = %s
"""


def send_delivery(delivery_id: int) -> None:
    """Entry point enqueued into RQ as `notifier.jobs.send_delivery`."""
    conn = get_connection()
    try:
        _send_delivery(conn, delivery_id)
    finally:
        conn.close()


def _send_delivery(conn: psycopg.Connection, delivery_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(_LOAD_DELIVERY_SQL, (delivery_id,))
        row = cur.fetchone()

    if row is None:
        logger.warning("delivery %s not found, skipping", delivery_id)
        return

    sender = SENDERS.get(row["channel_type"])
    if sender is None:
        _mark_failed(conn, delivery_id, f"unknown channel_type '{row['channel_type']}'")
        return

    watch = {"subject_type": row["subject_type"], "subject_value": row["subject_value"]}
    change_event = {
        "field_name": row["field_name"],
        "old_value": row["old_value"],
        "new_value": row["new_value"],
        "source_file": row["source_file"],
        "effective_date": row["effective_date"],
        "detected_at": row["detected_at"],
    }
    subject, body = render_message(watch, change_event)

    try:
        sender(row["config"], subject, body)
    except SendError as exc:
        _mark_failed(conn, delivery_id, str(exc))
        return
    except Exception as exc:  # defensive: a buggy/unexpected sender error still records last_error
        _mark_failed(conn, delivery_id, f"unexpected error: {exc}")
        return

    _mark_sent(conn, delivery_id)


def _mark_sent(conn: psycopg.Connection, delivery_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE notification_deliveries
            SET status = 'sent', attempts = attempts + 1, sent_at = now(), last_error = NULL
            WHERE id = %s
            """,
            (delivery_id,),
        )


def _mark_failed(conn: psycopg.Connection, delivery_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE notification_deliveries
            SET status = CASE WHEN attempts + 1 >= %s THEN 'failed' ELSE 'pending' END,
                attempts = attempts + 1,
                last_error = %s
            WHERE id = %s
            """,
            (settings.max_delivery_attempts, error, delivery_id),
        )


_LOAD_CHANNEL_SQL = "SELECT channel_type, config FROM notification_channels WHERE id = %s"


def send_test_message(channel_id: int) -> dict:
    """Entry point enqueued into RQ as `app.jobs.send_test_message` -- unlike
    `send_delivery`, this isn't tied to any real watch/change_event: it's
    enqueued directly by the api service (a separate container/codebase, so
    referenced here by string path rather than an imported function
    reference -- see api/app/routers/channels.py's test-send endpoint) when
    a signed-in user clicks "Send test" on one of their channels.

    Returns a small result dict on success (captured by RQ as the job's
    result, which the api endpoint polls for); raises on failure so RQ
    records it as a failed job with the exception available via
    `job.latest_result()`/`job.exc_info`.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_LOAD_CHANNEL_SQL, (channel_id,))
            row = cur.fetchone()

        if row is None:
            raise SendError(f"channel {channel_id} not found")

        sender = SENDERS.get(row["channel_type"])
        if sender is None:
            raise SendError(f"unknown channel_type '{row['channel_type']}'")

        subject, body = render_test_message(row["channel_type"])
        sender(row["config"], subject, body)

        # Set is_verified here (not just in the api's poll-success path) so
        # a slow external send (e.g. an ntfy.sh/SMTP relay taking longer
        # than the api's poll timeout -- observed ~11s for a plain ntfy.sh
        # POST during live testing, longer than the api's former 8s poll
        # window) still gets recorded as verified once it actually
        # succeeds, even if the api already gave up and told the user
        # "timeout". This is the source of truth; the api's poll-success
        # path is just a fast-path for the common case.
        with conn.cursor() as cur:
            cur.execute("UPDATE notification_channels SET is_verified = true WHERE id = %s", (channel_id,))
        conn.commit()

        return {"channel_type": row["channel_type"], "sent": True}
    finally:
        conn.close()
