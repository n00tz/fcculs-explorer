"""Ingest orchestration: parse a downloaded .dat file, diff each row against
the current DB state, upsert, and record change_events -- the pipeline that
turns a downloaded FCC file into both up-to-date tables and an alert trigger
log.
"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

import psycopg

from db import (
    fetch_existing_row,
    frn_has_prior_amateur_license,
    insert_change_event,
    upsert_row,
    upsert_rows_batch,
)
from differ import diff_rows
from parser import parse_dat_file

logger = logging.getLogger(__name__)

# Which parsed field identifies the "subject" for change_events/watches, per table.
SUBJECT_KEY_FIELD = {
    "amat_hd": "call_sign",
    "amat_en": "call_sign",
    "amat_am": "callsign",
    "tower_ra": "registration_number",
    "tower_en": "registration_number",
    "gmrs_hd": "call_sign",
    "gmrs_en": "call_sign",
    "aircr_hd": "call_sign",
    "aircr_en": "call_sign",
    "aircr_ac": "call_sign",
    "ship_hd": "call_sign",
    "ship_en": "call_sign",
    # FCC spells this column "callsign" (no underscore) in the SH record only.
    "ship_sh": "callsign",
    "ship_sr": "call_sign",
    "ship_sv": "call_sign",
    "ship_se": "call_sign",
}

SUBJECT_TYPE = {
    "amat_hd": "amateur_license",
    "amat_en": "amateur_license",
    "amat_am": "amateur_license",
    "tower_ra": "tower",
    "tower_en": "tower",
    "gmrs_hd": "gmrs_license",
    "gmrs_en": "gmrs_license",
    "aircr_hd": "aircraft_license",
    "aircr_en": "aircraft_license",
    "aircr_ac": "aircraft_license",
    "ship_hd": "ship_license",
    "ship_en": "ship_license",
    "ship_sh": "ship_license",
    "ship_sr": "ship_license",
    "ship_sv": "ship_license",
    "ship_se": "ship_license",
}

# Which service each table belongs to, stamped onto change_events so a watch
# can optionally be scoped to a single service (watches.service). Derived
# from the table prefix, which is stable by construction.
TABLE_SERVICE = {
    "amat": "amateur",
    "tower": "tower",
    "gmrs": "gmrs",
    "aircr": "aircraft",
    "ship": "ship",
}

# Tables carrying an FRN, and the synthetic change_events field_name emitted
# when a genuinely brand-new row (never seen before) appears for that table
# during a daily incremental ingest. This is how a "watch by FRN" (set up
# before a callsign/tower registration exists yet) gets notified: normal
# diff_rows() intentionally produces no events for brand-new rows (to avoid
# spamming "changed from nothing" for every field), so without this, a new
# licensee's first callsign grant would never fire any change_event at all.
#
# Only the *_en table of each service appears here: it is the one record that
# carries the FRN, and listing a service's other record types too would emit
# several duplicate "new licence" events for a single grant.
NEW_RECORD_FRN_EVENT = {
    "amat_en": "license_granted",
    "tower_en": "tower_registered",
    "gmrs_en": "gmrs_license_granted",
    "aircr_en": "aircraft_license_granted",
    "ship_en": "ship_license_granted",
}


def service_for_table(table: str) -> Optional[str]:
    """Map a raw table name to its service name ('amat_en' -> 'amateur')."""
    return TABLE_SERVICE.get(table.split("_", 1)[0])


def ingest_file(
    conn: psycopg.Connection,
    path: Path,
    record_def: dict,
    source_file: str,
    effective_date: date,
    generate_diffs: bool,
) -> dict:
    """Ingest one .dat file's rows into its target table.

    Returns a summary dict: {"rows": n, "changes": n, "inserted": n}.
    """
    table = record_def["table"]
    key_cols = record_def["key"]
    subject_field = SUBJECT_KEY_FIELD.get(table)
    subject_type = SUBJECT_TYPE.get(table)
    service = service_for_table(table)

    # Fast path: no diffing (bootstrap / complete-dump load). Every row is a
    # straight upsert, so batch them with executemany instead of doing a
    # per-row SELECT + INSERT -- orders of magnitude faster on the
    # multi-hundred-thousand-row weekly dumps. Semantics are identical for a
    # fresh/complete load: last-write-wins per key, no change_events.
    if not generate_diffs:
        written = upsert_rows_batch(
            conn,
            table,
            parse_dat_file(
                path,
                record_def["schema"],
                strict=False,
                record_type=record_def.get("record_type"),
            ),
            key_cols,
        )
        conn.commit()
        logger.info("%s: %d rows loaded (batch fast path)", path.name, written)
        return {"rows": written, "changes": 0, "inserted": written}

    rows = 0
    changes = 0
    inserted = 0

    for record in parse_dat_file(
        path,
        record_def["schema"],
        strict=False,
        record_type=record_def.get("record_type"),
    ):
        rows += 1
        existing = None
        if key_cols:
            key_values = {c: record.get(c) for c in key_cols}
            if all(v is not None for v in key_values.values()):
                existing = fetch_existing_row(conn, table, key_cols, key_values)

        if existing is None:
            inserted += 1
            # Brand-new record: no field-diff event (see NEW_RECORD_FRN_EVENT
            # comment above), but if this table carries an FRN, emit one
            # synthetic "a new asset appeared for this identity" event so a
            # watch set on that FRN (e.g. a brand-new ham who only knows
            # their FRN, before any callsign exists) actually fires.
            new_record_field = NEW_RECORD_FRN_EVENT.get(table)
            if generate_diffs and new_record_field and subject_field and subject_type:
                frn = (record.get("frn") or "").strip()
                if frn:
                    # "New ham"/"new club" celebration flag: only meaningful
                    # for amat_en (an amateur license grant) -- the concept
                    # doesn't apply to tower registrations. Checked BEFORE
                    # this record's own upsert_row() call below, so the row
                    # being evaluated is correctly excluded from its own
                    # existence check. Computed once here and never revisited
                    # later, so it can't retroactively flip if this FRN later
                    # gains a second/vanity callsign.
                    is_new_operator = (
                        table == "amat_en" and not frn_has_prior_amateur_license(conn, frn)
                    )
                    insert_change_event(
                        conn,
                        subject_type=subject_type,
                        subject_key=record.get(subject_field) or "",
                        uls_system_id=str(record.get("unique_system_identifier") or "") or None,
                        field_name=new_record_field,
                        old_value=None,
                        new_value=record.get(subject_field),
                        source_file=source_file,
                        effective_date=effective_date,
                        frn=frn,
                        is_new_operator=is_new_operator,
                        service=service,
                    )
                    changes += 1
        elif generate_diffs and subject_field and subject_type:
            field_changes = diff_rows(existing, record)
            for field_name, old_value, new_value in field_changes:
                insert_change_event(
                    conn,
                    subject_type=subject_type,
                    subject_key=record.get(subject_field) or "",
                    uls_system_id=str(record.get("unique_system_identifier") or "") or None,
                    field_name=field_name,
                    old_value=old_value,
                    new_value=new_value,
                    source_file=source_file,
                    effective_date=effective_date,
                    service=service,
                )
                changes += 1

        upsert_row(conn, table, record, key_cols)

    conn.commit()
    logger.info("%s: %d rows, %d new, %d field changes", path.name, rows, inserted, changes)
    return {"rows": rows, "changes": changes, "inserted": inserted}
