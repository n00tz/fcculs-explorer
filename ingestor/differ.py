"""Diff-before-upsert core: compares an incoming parsed row against the
currently stored row (if any) and returns per-field changes, before the
caller upserts the new row. This diff list is the direct source of
`change_events` rows that drive the alerting feature.
"""
from datetime import date
from typing import Optional


def diff_rows(old_row: Optional[dict], new_row: dict) -> list[tuple[str, object, object]]:
    """Return a list of (field_name, old_value, new_value) for every field
    that changed. If old_row is None (first time this key has been seen),
    no diff is produced -- there's nothing to alert on for a brand-new
    record during a bootstrap load, and daily loads that introduce a truly
    new callsign/tower shouldn't spam every field as "changed from nothing".
    """
    if old_row is None:
        return []
    changes = []
    for field, new_value in new_row.items():
        old_value = old_row.get(field)
        if _normalize(old_value) != _normalize(new_value):
            changes.append((field, old_value, new_value))
    return changes


def _normalize(value):
    """Normalize a value for comparison purposes only (the caller still
    reports the original old_value/new_value for storage/display).

    Two shape mismatches must be bridged here because one side of the
    comparison is always a freshly-parsed FCC row (plain strings, FCC's own
    MM/DD/YYYY date format) while the other is a row fetched back from
    Postgres (typed: datetime.date, int, Decimal, etc.):

    - None and empty string are treated as equivalent (trivial NULL<->''
      shape differences shouldn't generate spurious change events).
    - date/datetime values are reformatted to FCC's MM/DD/YYYY string so a
      DB-typed date and its equivalent freshly-parsed string compare equal;
      everything else (int, Decimal, str, ...) is compared as its string
      form so e.g. DB int 232195 == parsed str "232195".
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value.strftime("%m/%d/%Y")
    return str(value)
