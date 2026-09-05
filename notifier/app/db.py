"""Sync Postgres access for the notifier (RQ workers are simplest as sync
processes; this service does small, infrequent queries, not the high-volume
bulk loads the ingestor does)."""
import psycopg
from psycopg.rows import dict_row

from .config import settings


def get_connection() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row, autocommit=True)
