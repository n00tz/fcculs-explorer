"""Pipe-delimited `.dat` file parser for FCC ULS records.

Given a schema (ordered list of field names, see schemas.py) and a file
path, yields one dict per row with `record_type` stripped and blank strings
normalized to None (FCC files use empty fields, not explicit NULL markers).
"""
import csv
from pathlib import Path
from typing import Iterator


class RowFieldCountMismatch(ValueError):
    """Raised when a data row doesn't have the expected number of fields.

    FCC has historically only appended new trailing fields to records
    (see docs/fcc-data-reference.md), so a mismatch here likely means the
    schema in schemas.py is stale and needs re-verification against a fresh
    sample rather than being silently ignored.
    """


def parse_dat_file(path: Path, schema: list[str], strict: bool = True) -> Iterator[dict]:
    expected = len(schema)
    with open(path, encoding="latin-1", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        for line_num, row in enumerate(reader, start=1):
            if not row:
                continue
            if len(row) != expected:
                if strict:
                    raise RowFieldCountMismatch(
                        f"{path.name} line {line_num}: expected {expected} fields, got {len(row)}"
                    )
                # Tolerate extra trailing fields (schema drift) by truncating,
                # and pad missing trailing fields with None.
                if len(row) > expected:
                    row = row[:expected]
                else:
                    row = row + [""] * (expected - len(row))
            record = {name: (value if value != "" else None) for name, value in zip(schema, row)}
            record.pop("record_type", None)
            yield record
