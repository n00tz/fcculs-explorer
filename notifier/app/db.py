"""Sync Postgres access for the notifier (RQ workers are simplest as sync
processes; this service does small, infrequent queries, not the high-volume
bulk loads the ingestor does)."""
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings


def get_connection() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row, autocommit=True)


def record_heartbeat(conn: psycopg.Connection, service: str, detail: dict | None = None) -> None:
    """Upsert a heartbeat row for a background loop (see db/011_ops_heartbeats.sql).

    Must be called unconditionally on every dispatch cycle, whether or not
    anything was enqueued -- a stale row here means the dispatch loop
    itself stopped running, which is a different (and more urgent)
    condition than "ran, but nothing new to send". `conn` is autocommit, so
    no explicit commit is needed.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO service_heartbeats (service, last_run_at, detail, updated_at)
            VALUES (%s, now(), %s, now())
            ON CONFLICT (service) DO UPDATE SET
                last_run_at = EXCLUDED.last_run_at,
                detail = EXCLUDED.detail,
                updated_at = now()
            """,
            (service, Jsonb(detail) if detail is not None else None),
        )

