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
            "SELECT subject_type, subject_key, field_name, old_value, new_value, frn, is_new_operator "
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
        assert rows[0][6] is True, "first-ever amat_en row for this FRN must be flagged is_new_operator=true"

    print("ALL WATCH-BY-FRN CHECKS PASSED")

    # 4. "New hams" celebration flag must NOT retroactively fire for a
    #    SECOND callsign granted to an ALREADY-KNOWN FRN (e.g. a vanity
    #    callsign) -- proves is_new_operator correctly tells a true
    #    first-timer apart from an existing licensee's additional callsign.
    second_en_row = (
        b"EN|999998|||N0OTZ|L|L09999998|TESTUSER, NEW E|NEW|E|TESTUSER|||||"
        b"1 New Ham Way|RINGGOLD|GA|30736|||000|0009999999|I||||||\n"
    )
    daily_en_path2 = Path("/tmp/daily_EN2.dat")
    daily_en_path2.write_bytes(en_content + new_en_row + second_en_row)

    result5 = ingest_file(
        conn, daily_en_path2,
        {"schema": schemas.AMAT_EN, "table": "amat_en", "key": ["unique_system_identifier"]},
        source_file="l_am_wed.zip", effective_date=date(2026, 9, 4), generate_diffs=True,
    )
    print("EN daily load (second callsign, same FRN) OK:", result5)
    assert result5["inserted"] == 1, result5  # only the brand-new N0OTZ row; KJ4KLO already exists

    with conn.cursor() as cur:
        cur.execute(
            "SELECT subject_key, is_new_operator FROM change_events "
            "WHERE frn = '0009999999' ORDER BY detected_at"
        )
        rows = cur.fetchall()
        print("second-callsign change_events rows:", rows)
        assert len(rows) == 2
        assert rows[0][0] == "KJ4KLO" and rows[0][1] is True
        assert rows[1][0] == "N0OTZ" and rows[1][1] is False, (
            "a second callsign for an already-known FRN must NOT be flagged is_new_operator"
        )

    print("ALL NEW-HAMS CELEBRATION FLAG CHECKS PASSED")

    check_advisory_lock_prevents_duplicate_events(conn)
    check_complete_dump_observation(conn)


def check_advisory_lock_prevents_duplicate_events(conn):
    """The regression test for the reason polling needs a lock at all.

    `change_events` has no unique constraint, and differ.diff_rows()
    compares each row against the CURRENTLY STORED row. Two ingests of the
    same day that interleave -- both reading the old row before either
    upserts -- therefore each emit a full set of change events, and the
    notifier turns those into DUPLICATE USER ALERTS. Under the old daily
    cron that was effectively impossible; polling every 15 minutes makes a
    slow run overlapping the next tick, or a poll racing an operator's
    manual --catch-up, entirely plausible.

    This uses two REAL Postgres sessions, not mocks: the whole point is
    that the mutual exclusion is enforced by the database, and a mocked
    lock would prove nothing about that.
    """
    from db import ingest_advisory_lock

    second = psycopg.connect(DSN)
    try:
        with ingest_advisory_lock(conn) as first_acquired:
            assert first_acquired is True, "first session must acquire the ingest lock"
            with ingest_advisory_lock(second) as second_acquired:
                assert second_acquired is False, (
                    "a second concurrent session MUST NOT acquire the ingest lock -- "
                    "without this, overlapping ingests emit duplicate change_events "
                    "and users receive duplicate alerts"
                )

        # Once the first session releases it, the lock is available again --
        # proving it is not leaked and does not need manual cleanup.
        with ingest_advisory_lock(second) as reacquired:
            assert reacquired is True, "lock must be released when the ingest finishes"
    finally:
        second.close()

    print("ALL ADVISORY LOCK CHECKS PASSED")


def check_complete_dump_observation(conn):
    """The poller records the newest weekly complete dump it sees so an
    operator can decide whether to re-bootstrap. It must report 'new' only
    once per dump, or the log would announce the same snapshot every hour.
    """
    from datetime import datetime, timedelta, timezone

    from db import latest_complete_dumps, record_complete_dump

    first_seen = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
    assert record_complete_dump(conn, "amateur", "l_amat.zip", first_seen, 197_000_000) is True

    # Same dump observed again on the next sweep: not news.
    assert record_complete_dump(conn, "amateur", "l_amat.zip", first_seen, 197_000_000) is False

    newer = first_seen + timedelta(days=7)
    assert record_complete_dump(conn, "amateur", "l_amat.zip", newer, 198_000_000) is True

    recorded = latest_complete_dumps(conn)
    assert recorded["amateur"]["published_at"] == newer, recorded
    assert recorded["amateur"]["size_bytes"] == 198_000_000, recorded

    print("ALL COMPLETE-DUMP OBSERVATION CHECKS PASSED")


if __name__ == "__main__":
    main()
