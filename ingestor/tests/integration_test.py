"""End-to-end integration test for the ingestor: runs a simulated 'bootstrap'
load (no diffs expected) followed by a simulated 'daily' load with a modified
row (expect a change_events row), against a real Postgres instance.
"""
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, "/app")

import psycopg
from ingest import ingest_file
import schemas

DSN = os.environ.get("DATABASE_URL", "postgresql://postgres:test@postgres:5432/fcculs_test")


def main():
    conn = psycopg.connect(DSN)

    fixtures = Path("/app/tests/fixtures")

    # 1. Bootstrap load: ingest amat_HD.dat fresh, no diffs expected (first-seen rows).
    result = ingest_file(
        conn, fixtures / "amat_HD.dat",
        {"schema": schemas.AMAT_HD, "table": "amat_hd", "key": ["unique_system_identifier"]},
        source_file="l_amat.zip", effective_date=date(2026, 9, 1), generate_diffs=False,
    )
    assert result["rows"] == 5, result
    assert result["changes"] == 0, result
    print("Bootstrap load OK:", result)

    with conn.cursor() as cur:
        cur.execute("SELECT license_status FROM amat_hd WHERE call_sign = 'K0WNL'")
        assert cur.fetchone()[0] == "A"

    # 2. Simulate a daily transaction file with K0WNL's status changed from A to E
    #    (e.g. license expired) -- everything else identical.
    daily_content = fixtures.joinpath("amat_HD.dat").read_bytes()
    modified = daily_content.replace(
        b"HD|232195|0012170403||K0WNL|A|HA|", b"HD|232195|0012170403||K0WNL|E|HA|", 1
    )
    daily_path = Path("/tmp/daily_HD.dat")
    daily_path.write_bytes(modified)

    result2 = ingest_file(
        conn, daily_path,
        {"schema": schemas.AMAT_HD, "table": "amat_hd", "key": ["unique_system_identifier"]},
        source_file="l_am_mon.zip", effective_date=date(2026, 9, 2), generate_diffs=True,
    )
    print("Daily load OK:", result2)
    assert result2["changes"] == 1, result2

    with conn.cursor() as cur:
        cur.execute("SELECT license_status FROM amat_hd WHERE call_sign = 'K0WNL'")
        assert cur.fetchone()[0] == "E"

        cur.execute(
            "SELECT subject_type, subject_key, field_name, old_value, new_value, source_file "
            "FROM change_events WHERE subject_key = 'K0WNL'"
        )
        rows = cur.fetchall()
        print("change_events rows:", rows)
        assert len(rows) == 1
        assert rows[0][2] == "license_status"
        assert rows[0][3] == "A"
        assert rows[0][4] == "E"

    print("ALL INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    main()
