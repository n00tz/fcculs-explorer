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
    is_new_operator: bool = False,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO change_events
                (subject_type, subject_key, uls_system_id, field_name, old_value, new_value, source_file, effective_date, frn, is_new_operator)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (subject_type, subject_key, uls_system_id, field_name,
             str(old_value) if old_value is not None else None,
             str(new_value) if new_value is not None else None,
             source_file, effective_date, frn or None, is_new_operator),
        )


def frn_has_prior_amateur_license(conn: psycopg.Connection, frn: str) -> bool:
    """True if amat_en already has ANY row for this FRN.

    Must be called BEFORE the new row's own upsert_row() runs in ingest.py's
    loop, so the brand-new row being evaluated is correctly excluded from its
    own check (this ordering is already guaranteed today -- see ingest.py).
    Used to durably flag a change_events row as "first-ever amat_en record
    for this FRN" (a "new ham"/"new club" celebration), computed once at
    ingest time so it never retroactively changes if this FRN later gains a
    second/vanity callsign.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS(SELECT 1 FROM amat_en WHERE frn = %s)", (frn,))
        return bool(cur.fetchone()[0])


def already_ingested(conn: psycopg.Connection, service: str, data_date: date) -> bool:
    """True if this service's transactions for this real calendar date have
    already been successfully ingested (see db/007_ingest_run_tracking.sql).

    This is the dedupe gate that makes catch-up runs safe to invoke as often
    as desired: FCC's weekday-named daily files rotate in place, so without
    tracking the real data date, a re-run would happily re-ingest whatever
    that weekday's file currently holds.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT EXISTS(SELECT 1 FROM ingest_runs WHERE service = %s AND data_date = %s AND status = 'success')",
            (service, data_date),
        )
        return bool(cur.fetchone()[0])


def ingested_data_dates(conn: psycopg.Connection, service: str, since: date) -> set:
    """All successfully-ingested data dates for a service on/after `since`.
    Fetched in one query so a catch-up pass doesn't issue a round trip per
    candidate day."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT data_date FROM ingest_runs WHERE service = %s AND data_date >= %s AND status = 'success'",
            (service, since),
        )
        return {r[0] for r in cur.fetchall()}


def record_ingest_run(
    conn: psycopg.Connection,
    service: str,
    day_of_week: str,
    data_date: date,
    source_file: str,
    last_modified=None,
    content_sha256: Optional[str] = None,
    rows_ingested: int = 0,
    changes_recorded: int = 0,
    status: str = "success",
) -> None:
    """Record that a service's daily file for a real calendar date was
    ingested. Upserts on (service, data_date) so a re-run refreshes the
    bookkeeping rather than raising on the unique constraint."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_runs
                (service, day_of_week, data_date, source_file, last_modified,
                 content_sha256, rows_ingested, changes_recorded, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (service, data_date) DO UPDATE SET
                day_of_week = EXCLUDED.day_of_week,
                source_file = EXCLUDED.source_file,
                last_modified = EXCLUDED.last_modified,
                content_sha256 = EXCLUDED.content_sha256,
                rows_ingested = EXCLUDED.rows_ingested,
                changes_recorded = EXCLUDED.changes_recorded,
                status = EXCLUDED.status,
                ingested_at = now()
            """,
            (service, day_of_week, data_date, source_file, last_modified,
             content_sha256, rows_ingested, changes_recorded, status),
        )
    conn.commit()
