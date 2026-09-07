"""Validate the declared record layouts against real FCC sample data.

Checks that every row of every file splits into exactly the number of fields
the schema declares. This is how a silent FCC layout change gets caught
before it corrupts a nightly ingest.

Usage:
    python validate_schema.py                       # this project's fixtures
    python validate_schema.py <dir>                 # a dir of "<svc>_<REC>.dat"
    python validate_schema.py <dir> --service ship  # a raw extracted FCC dump
"""
import argparse
import sys
from pathlib import Path

from parser import _logical_lines
from schemas import SERVICES

# Filename prefix used by this project's test fixtures, per service.
SERVICE_PREFIX = {
    "amateur": "amat",
    "tower": "tower",
    "gmrs": "gmrs",
    "aircraft": "aircr",
    "ship": "ship",
}

# A few rows in every real dump contain an unescaped '|' inside a free-text
# field (FCC applies no escaping or quoting). Verified 2026-09-07: 17 such
# rows across 5.6M. That is data noise, not a layout change -- but a large
# proportion of mismatches means the schema is genuinely wrong, so tolerate
# only a tiny fraction.
MISMATCH_TOLERANCE = 0.001


def validate_file(path: Path, expected_count: int, record_type: str) -> bool:
    """Return True if the file matches its declared layout."""
    row_count = 0
    mismatches = 0
    for line_num, raw in enumerate(_logical_lines(path, record_type), start=1):
        row_count += 1
        actual = len(raw.split("|"))
        if actual != expected_count:
            mismatches += 1
            if mismatches <= 5:
                print(
                    f"  MISMATCH {path.name} line {line_num}: "
                    f"expected {expected_count} fields, got {actual}"
                )
    if not mismatches:
        print(f"  OK {path.name}: {row_count} rows, {expected_count} fields/row")
        return True
    within_tolerance = mismatches <= max(1, row_count * MISMATCH_TOLERANCE)
    print(
        f"  {'WARN' if within_tolerance else 'FAIL'} {path.name}: "
        f"{mismatches}/{row_count} rows mismatched"
        + (" (likely unescaped '|' in free text)" if within_tolerance else "")
    )
    return within_tolerance


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory", nargs="?", default="tests/fixtures")
    ap.add_argument(
        "--service", choices=sorted(SERVICES),
        help=(
            "validate a raw extracted FCC dump, whose files are named "
            "'<REC>.dat' with no service prefix. Required for such a "
            "directory, since HD.dat/EN.dat are ambiguous without it."
        ),
    )
    args = ap.parse_args()
    source_dir = Path(args.directory)

    services = [args.service] if args.service else list(SERVICES)
    ok = True
    checked = 0
    for service in services:
        for filename, meta in SERVICES[service].items():
            expected = len(meta["schema"])
            # A raw FCC extract uses the bare record name; this project's
            # fixtures prefix it with the service so several services can
            # share one directory without HD.dat colliding.
            name = filename if args.service else f"{SERVICE_PREFIX[service]}_{filename}"
            path = source_dir / name
            if not path.exists():
                print(f"  SKIP {name}: not found in {source_dir}")
                continue
            checked += 1
            ok &= validate_file(path, expected, meta["record_type"])
    print(f"\n{checked} file(s) checked -- {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
