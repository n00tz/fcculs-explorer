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
        cur.execute("SELECT license_status FROM amat_hd WHERE call_sign = 'KM4TYD'")
        assert cur.fetchone()[0] == "A"

    # 2. Simulate a daily transaction file with KM4TYD's status changed from A to E
    #    (e.g. license expired) -- everything else identical.
    daily_content = fixtures.joinpath("amat_HD.dat").read_bytes()
    modified = daily_content.replace(
        b"HD|232195|0012170403||KM4TYD|A|HA|", b"HD|232195|0012170403||KM4TYD|E|HA|", 1
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
        cur.execute("SELECT license_status FROM amat_hd WHERE call_sign = 'KM4TYD'")
        assert cur.fetchone()[0] == "E"

        cur.execute(
            "SELECT subject_type, subject_key, field_name, old_value, new_value, source_file "
            "FROM change_events WHERE subject_key = 'KM4TYD'"
        )
        rows = cur.fetchall()
        print("change_events rows:", rows)
        assert len(rows) == 1
        assert rows[0][2] == "license_status"
        assert rows[0][3] == "A"
        assert rows[0][4] == "E"

    print("ALL INTEGRATION CHECKS PASSED")

    # 3. Watch-by-FRN support: bootstrap-load amat_EN.dat (5 existing rows,
    #    no diffs expected on first load), then simulate a daily EN file
    #    that adds one brand-new row (a new USID/callsign never seen
    #    before) carrying an FRN -- expect exactly one synthetic
    #    'license_granted' change_events row for that FRN, and confirm the
    #    modified existing rows produce ordinary per-field diffs, not a
    #    second synthetic event.
    result3 = ingest_file(
        conn, fixtures / "amat_EN.dat",
        {"schema": schemas.AMAT_EN, "table": "amat_en", "key": ["unique_system_identifier"]},
        source_file="l_amat.zip", effective_date=date(2026, 9, 1), generate_diffs=False,
    )
    assert result3["rows"] == 5, result3
    assert result3["changes"] == 0, result3
    print("EN bootstrap load OK:", result3)

    en_content = fixtures.joinpath("amat_EN.dat").read_bytes()
    new_en_row = (
        b"EN|999999|||KJ4KLO|L|L09999999|TESTUSER, NEW E|NEW|E|TESTUSER|||||"
        b"1 New Ham Way|RINGGOLD|GA|30736|||000|0009999999|I||||||\n"
    )
    daily_en_path = Path("/tmp/daily_EN.dat")
    daily_en_path.write_bytes(en_content + new_en_row)

    result4 = ingest_file(
        conn, daily_en_path,
        {"schema": schemas.AMAT_EN, "table": "amat_en", "key": ["unique_system_identifier"]},
        source_file="l_am_tue.zip", effective_date=date(2026, 9, 3), generate_diffs=True,
    )
    print("EN daily load (new record) OK:", result4)
    assert result4["inserted"] == 1, result4
    assert result4["changes"] == 1, result4

    with conn.cursor() as cur:
        cur.execute(
            "SELECT subject_type, subject_key, field_name, old_value, new_value, frn "
            "FROM change_events WHERE frn = '0009999999'"
        )
        rows = cur.fetchall()
        print("frn change_events rows:", rows)
        assert len(rows) == 1
        assert rows[0][0] == "amateur_license"
        assert rows[0][1] == "KJ4KLO"
        assert rows[0][2] == "license_granted"
        assert rows[0][3] is None
        assert rows[0][4] == "KJ4KLO"
        assert rows[0][5] == "0009999999"

    print("ALL WATCH-BY-FRN CHECKS PASSED")


if __name__ == "__main__":
    main()
