"""Database access layer for the ingestor: fetch-before-upsert + change_events.

Uses psycopg (v3) with plain SQL -- no ORM, since every table/row shape here
is a straight passthrough of parsed FCC records (see schemas.py).
"""
from datetime import date
from typing import Optional

import psycopg


def fetch_existing_row(conn: psycopg.Connection, table: str, key_cols: list[str], key_values: dict) -> Optional[dict]:
    where_clause = " AND ".join(f"{col} = %s" for col in key_cols)
    params = [key_values[col] for col in key_cols]
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(f"SELECT * FROM {table} WHERE {where_clause}", params)
        return cur.fetchone()


def upsert_row(conn: psycopg.Connection, table: str, row: dict, key_cols: Optional[list[str]]) -> None:
    columns = list(row.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    col_list = ", ".join(columns)
    if key_cols:
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in key_cols)
        update_clause += ", updated_at = now()"
        conflict_cols = ", ".join(key_cols)
        sql = (
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_clause}"
        )
    else:
        # No natural key (e.g. append-only history logs like amat_hs) -- plain insert.
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, list(row.values()))


def insert_change_event(
    conn: psycopg.Connection,
    subject_type: str,
    subject_key: str,
    uls_system_id: Optional[str],
    field_name: str,
    old_value,
    new_value,
    source_file: str,
    effective_date: date,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO change_events
                (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (subject_type, subject_key, uls_system_id, field_name,
             str(old_value) if old_value is not None else None,
             str(new_value) if new_value is not None else None,
             source_file, effective_date),
        )
