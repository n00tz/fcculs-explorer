"""Minimal parser/loader prototype for validating the FCC ULS schema design
against real sample data (docs/fcc-data-reference.md). This is a schema
validation script, not the production ingestor (see build-ingestor todo for
the full downloader + diff + change_events implementation).

Usage:
    python validate_schema.py <fixtures_dir>
"""
import csv
import sys
from pathlib import Path

# Column orders as documented in db/002_fcc_raw_tables.sql, used here only
# to sanity-check that real fixture rows split into the expected number of
# fields per record type.
EXPECTED_FIELD_COUNTS = {
    "amat_HD.dat": 59,
    "amat_EN.dat": 30,
    "amat_AM.dat": 18,
    "amat_HS.dat": 6,
    "tower_RA.dat": 49,
    "tower_EN.dat": 25,
    "tower_CO.dat": 18,
}


def validate_file(path: Path, expected_count: int) -> None:
    with open(path, encoding="latin-1", newline="") as f:
        reader = csv.reader(f, delimiter="|")
        row_count = 0
        for row in reader:
            if len(row) != expected_count:
                print(
                    f"  MISMATCH {path.name} line {row_count + 1}: "
                    f"expected {expected_count} fields, got {len(row)}"
                )
            row_count += 1
        print(f"  OK {path.name}: {row_count} rows, {expected_count} fields/row expected")


def main() -> None:
    fixtures_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "tests/fixtures")
    for filename, expected in EXPECTED_FIELD_COUNTS.items():
        path = fixtures_dir / filename
        if not path.exists():
            print(f"  SKIP {filename}: not found in {fixtures_dir}")
            continue
        validate_file(path, expected)


if __name__ == "__main__":
    main()
