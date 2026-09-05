"""The RQ job body: delivers one pending notification_deliveries row and
updates its status. Designed to be idempotent-safe under RQ retries -- a
retry simply re-attempts the same delivery id, incrementing attempts."""
import logging

import psycopg

from .config import settings
from .db import get_connection
from .render import render_message
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
