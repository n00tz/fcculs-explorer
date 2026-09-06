"""Matches new change_events against active watches and records a pending
notification_deliveries row for each new (watch, change_event) pair.

Idempotent by design: re-running finds only pairs with no existing delivery
row yet (enforced by a DB unique constraint on (watch_id, change_event_id)),
so it's safe to call repeatedly (e.g. on a timer) without double-queuing.
"""
import psycopg

_MATCH_SQL = """
SELECT w.id AS watch_id, ce.id AS change_event_id
FROM change_events ce
JOIN watches w ON w.is_active
    AND (
        (w.subject_type IN ('callsign', 'asr_registration_number') AND w.subject_value = ce.subject_key)
        OR (w.subject_type = 'uls_id' AND w.subject_value = ce.uls_system_id)
        OR (w.subject_type = 'frn' AND w.subject_value = ce.frn)
    )
LEFT JOIN notification_deliveries nd
    ON nd.watch_id = w.id AND nd.change_event_id = ce.id
WHERE nd.id IS NULL
"""


def find_new_matches(conn: psycopg.Connection) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(_MATCH_SQL)
        return cur.fetchall()


def record_pending_deliveries(conn: psycopg.Connection, matches: list[dict]) -> list[int]:
    """Insert a pending notification_deliveries row per match. Uses
    ON CONFLICT DO NOTHING as a second idempotency guard (in case of a race
    between two concurrent matcher runs) and returns the ids of rows that
    were actually newly created (safe to enqueue)."""
    if not matches:
        return []
    new_ids: list[int] = []
    with conn.cursor() as cur:
        for match in matches:
            cur.execute(
                """
                INSERT INTO notification_deliveries (watch_id, change_event_id)
                VALUES (%s, %s)
                ON CONFLICT (watch_id, change_event_id) DO NOTHING
                RETURNING id
                """,
                (match["watch_id"], match["change_event_id"]),
            )
            row = cur.fetchone()
            if row:
                new_ids.append(row["id"])
    return new_ids


def match_and_record(conn: psycopg.Connection) -> list[int]:
    """Convenience wrapper: find matches, record pending deliveries, return
    the ids of newly created deliveries ready to be enqueued."""
    matches = find_new_matches(conn)
    return record_pending_deliveries(conn, matches)
