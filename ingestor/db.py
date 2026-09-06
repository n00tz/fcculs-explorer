"""Database access layer for the ingestor: fetch-before-upsert + change_events.

Uses psycopg (v3) with plain SQL -- no ORM, since every table/row shape here
is a straight passthrough of parsed FCC records (see schemas.py).
"""
from datetime import date
from typing import Iterable, Optional

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


def _upsert_sql(table: str, columns: list[str], key_cols: Optional[list[str]]) -> str:
    col_list = ", ".join(columns)
    placeholders = "(" + ", ".join(["%s"] * len(columns)) + ")"
    if key_cols:
        update_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c not in key_cols)
        update_clause += ", updated_at = now()"
        conflict_cols = ", ".join(key_cols)
        return (
            f"INSERT INTO {table} ({col_list}) VALUES {placeholders} "
            f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_clause}"
        )
    return f"INSERT INTO {table} ({col_list}) VALUES {placeholders}"


def upsert_rows_batch(
    conn: psycopg.Connection,
    table: str,
    rows: Iterable[dict],
    key_cols: Optional[list[str]],
    batch_size: int = 2000,
) -> int:
    """Batched upsert using psycopg's server-side executemany -- used on the
    no-diff path (bootstrap / complete dumps) where per-row SELECT+diff would
    be prohibitively slow on multi-hundred-thousand-row files. Rows must all
    share the same column set (guaranteed by the parser for a given file).
    Returns the number of rows written."""
    it = iter(rows)
    first = next(it, None)
    if first is None:
        return 0
    columns = list(first.keys())
    sql = _upsert_sql(table, columns, key_cols)
    count = 0

    def values(r):
        return tuple(r[c] for c in columns)

    with conn.cursor() as cur:
        batch = [values(first)]
        for r in it:
            batch.append(values(r))
            if len(batch) >= batch_size:
                cur.executemany(sql, batch)
                count += len(batch)
                batch.clear()
        if batch:
            cur.executemany(sql, batch)
            count += len(batch)
    return count


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
    frn: Optional[str] = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO change_events
                (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (subject_type, subject_key, uls_system_id, field_name,
             str(old_value) if old_value is not None else None,
             str(new_value) if new_value is not None else None,
             source_file, effective_date, frn or None),
        )
