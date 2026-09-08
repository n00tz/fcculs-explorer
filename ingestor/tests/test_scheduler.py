"""Unit tests for the scheduler's catch-up orchestration and for resolving
which real calendar date each weekday-named FCC daily file actually holds.

Mocks network/DB; verifies the HEAD -> resolve-date -> skip-already-ingested
-> download -> ingest -> record wiring, not the ingestion logic itself (which
is already covered by test_parser/test_differ).
"""
import contextlib
import datetime
import sys
import unittest
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import downloader
import parser
import scheduler


def _utc(y, m, d, hh=12, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.timezone.utc)


@contextlib.contextmanager
def _fake_lock(acquired: bool):
    """Stand-in for db.ingest_advisory_lock in tests that don't need a real
    Postgres session."""
    yield acquired


class TestResolveDailyDataDate(unittest.TestCase):
    """FCC publishes `{prefix}_{dow}.zip` about noon UTC the day AFTER the
    weekday it is named for, and rotates it in place weekly. These cases use
    the real Last-Modified values observed on data.fcc.gov on 2026-09-07."""

    def test_monday_file_published_tuesday_resolves_to_that_monday(self):
        # Observed: l_am_mon.zip Last-Modified Tue, 01 Sep 2026 12:00:09 GMT
        self.assertEqual(
            downloader.resolve_daily_data_date("mon", _utc(2026, 9, 1)),
            datetime.date(2026, 8, 31),
        )

    def test_sunday_file_published_monday_resolves_to_that_sunday(self):
        # Observed: l_am_sun.zip Last-Modified Mon, 07 Sep 2026 12:00:10 GMT
        self.assertEqual(
            downloader.resolve_daily_data_date("sun", _utc(2026, 9, 7)),
            datetime.date(2026, 9, 6),
        )

    def test_full_week_of_observed_headers_maps_to_seven_consecutive_days(self):
        observed = {
            "mon": _utc(2026, 9, 1),
            "tue": _utc(2026, 9, 2),
            "wed": _utc(2026, 9, 3),
            "thu": _utc(2026, 9, 4),
            "fri": _utc(2026, 9, 5, 8),
            "sat": _utc(2026, 9, 6, 13),
            "sun": _utc(2026, 9, 7),
        }
        resolved = sorted(
            downloader.resolve_daily_data_date(dow, lm) for dow, lm in observed.items()
        )
        # The seven weekday files together cover exactly Aug 31 .. Sep 6.
        self.assertEqual(resolved[0], datetime.date(2026, 8, 31))
        self.assertEqual(resolved[-1], datetime.date(2026, 9, 6))
        self.assertEqual(len(set(resolved)), 7)
        for earlier, later in zip(resolved, resolved[1:]):
            self.assertEqual((later - earlier).days, 1)

    def test_late_publication_still_resolves_to_correct_weekday(self):
        # If FCC published Monday's file late (on Wednesday), it must still
        # resolve to Monday -- not to "publish date minus one day" (Tuesday).
        self.assertEqual(
            downloader.resolve_daily_data_date("mon", _utc(2026, 9, 2)),
            datetime.date(2026, 8, 31),
        )

    def test_missing_last_modified_returns_none_rather_than_guessing(self):
        self.assertIsNone(downloader.resolve_daily_data_date("mon", None))

    def test_invalid_day_of_week_rejected(self):
        with self.assertRaises(ValueError):
            downloader.resolve_daily_data_date("funday", _utc(2026, 9, 1))


class TestDiscoverAvailableDays(unittest.TestCase):
    @patch("scheduler.head_daily")
    def test_returns_all_seven_days_sorted_oldest_first(self, mock_head):
        published = {
            "mon": _utc(2026, 9, 1), "tue": _utc(2026, 9, 2), "wed": _utc(2026, 9, 3),
            "thu": _utc(2026, 9, 4), "fri": _utc(2026, 9, 5), "sat": _utc(2026, 9, 6),
            "sun": _utc(2026, 9, 7),
        }
        mock_head.side_effect = lambda service, dow: {
            "last_modified": published[dow], "size": 1234, "etag": None
        }

        result = scheduler.discover_available_days("amateur")

        self.assertEqual(len(result), 7)
        dates = [data_date for _, data_date, _ in result]
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates[0], datetime.date(2026, 8, 31))
        self.assertEqual(dates[-1], datetime.date(2026, 9, 6))

    @patch("scheduler.head_daily")
    def test_failing_head_is_skipped_and_undateable_file_is_deferred(self, mock_head):
        """A HEAD failure drops that weekday; a file with no usable
        Last-Modified is NOT dropped.

        Undateable files used to be skipped outright, which made them
        invisible forever. They are now carried through with data_date=None
        so the ingest path can date them from the archive's own `counts`
        member after download (see scheduler._ingest_one_day).
        """
        def fake_head(service, dow):
            if dow == "wed":
                raise RuntimeError("connection reset")
            if dow == "thu":
                return {"last_modified": None, "size": None, "etag": None}
            return {"last_modified": _utc(2026, 9, 7), "size": 1, "etag": None}

        mock_head.side_effect = fake_head
        result = scheduler.discover_available_days("amateur")

        by_day = {dow: data_date for dow, data_date, _ in result}
        self.assertNotIn("wed", by_day)  # HEAD failed outright
        self.assertIn("thu", by_day)  # deferred, not discarded
        self.assertIsNone(by_day["thu"])
        self.assertEqual(len(result), 6)
        # Undateable entries sort last so the dateable days are still
        # ingested oldest-first.
        self.assertIsNone(result[-1][1])


class TestRunDailyJobCatchUp(unittest.TestCase):
    def _patch_common(self):
        """Patch the network/DB seams shared by the catch-up tests."""
        patches = {
            "connect": patch("scheduler.psycopg.connect"),
            "discover": patch("scheduler.discover_available_days"),
            "ingested": patch("scheduler.ingested_data_dates"),
            "record": patch("scheduler.record_ingest_run"),
            "download": patch("scheduler.download_daily"),
            "extract": patch("scheduler.extract_zip"),
            "ingest": patch("scheduler.ingest_file"),
            "refresh": patch("scheduler._refresh_materialized_views"),
            "counts": patch("scheduler.read_archive_counts"),
            "lock": patch("scheduler.ingest_advisory_lock"),
        }
        started = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

        started["connect"].return_value = MagicMock()
        started["download"].return_value = b"fake zip bytes"
        started["extract"].side_effect = lambda content, dest_dir: [
            dest_dir / n for n in ["HD.dat", "EN.dat", "AM.dat", "HS.dat", "RA.dat", "CO.dat"]
        ]
        started["ingest"].return_value = {"rows": 5, "changes": 1, "inserted": 0}
        # No `counts` member -> no integrity oracle -> status stays 'success'.
        # Tests that care about the check set this explicitly.
        started["counts"].return_value = parser.ArchiveCounts(rows={}, created_at=None)
        started["lock"].side_effect = lambda conn: _fake_lock(True)
        return started

    def test_ingests_only_days_not_already_recorded_oldest_first(self):
        m = self._patch_common()
        # FCC currently offers Sep 3, 4, 5; Sep 3 was already ingested.
        m["discover"].return_value = [
            ("thu", datetime.date(2026, 9, 3), _utc(2026, 9, 4)),
            ("fri", datetime.date(2026, 9, 4), _utc(2026, 9, 5)),
            ("sat", datetime.date(2026, 9, 5), _utc(2026, 9, 6)),
        ]
        m["ingested"].return_value = {datetime.date(2026, 9, 3)}

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7),
                                services=["amateur", "tower"])

        ingested_dates = [c.kwargs["data_date"] for c in m["record"].call_args_list]
        # Two services x two pending days each, and never the already-done day.
        # Services are pinned explicitly so this stays deterministic as more
        # services are added to SERVICES.
        self.assertNotIn(datetime.date(2026, 9, 3), ingested_dates)
        self.assertEqual(
            ingested_dates,
            [datetime.date(2026, 9, 4), datetime.date(2026, 9, 5)] * 2,
        )

    def test_effective_date_is_the_files_real_data_date_not_the_run_date(self):
        """The original bug: a week-old file was ingested stamped as today."""
        m = self._patch_common()
        m["discover"].return_value = [("mon", datetime.date(2026, 8, 31), _utc(2026, 9, 1))]
        m["ingested"].return_value = set()

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))

        effective_dates = {c.kwargs["effective_date"] for c in m["ingest"].call_args_list}
        self.assertEqual(effective_dates, {datetime.date(2026, 8, 31)})
        self.assertNotIn(datetime.date(2026, 9, 7), effective_dates)

    def test_nothing_pending_skips_download_and_view_refresh(self):
        m = self._patch_common()
        m["discover"].return_value = [("sat", datetime.date(2026, 9, 5), _utc(2026, 9, 6))]
        m["ingested"].return_value = {datetime.date(2026, 9, 5)}

        result = scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))

        m["download"].assert_not_called()
        m["record"].assert_not_called()
        m["refresh"].assert_not_called()
        self.assertEqual(result, {})

    def test_days_older_than_the_rolling_window_are_ignored(self):
        m = self._patch_common()
        m["discover"].return_value = [
            ("mon", datetime.date(2026, 8, 20), _utc(2026, 8, 21)),  # way outside window
            ("sat", datetime.date(2026, 9, 5), _utc(2026, 9, 6)),
        ]
        m["ingested"].return_value = set()

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))

        ingested_dates = {c.kwargs["data_date"] for c in m["record"].call_args_list}
        self.assertEqual(ingested_dates, {datetime.date(2026, 9, 5)})

    def test_missing_expected_file_is_skipped_not_fatal(self):
        m = self._patch_common()
        m["discover"].return_value = [("sat", datetime.date(2026, 9, 5), _utc(2026, 9, 6))]
        m["ingested"].return_value = set()
        m["extract"].side_effect = lambda content, dest_dir: []  # nothing in archive

        result = scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7),
                                         services=["amateur", "tower"])

        m["ingest"].assert_not_called()
        self.assertEqual(result, {})
        # The day is still recorded, so an empty/holiday archive isn't retried forever.
        self.assertEqual(m["record"].call_count, 2)  # one per pinned service

    def test_records_run_metadata_for_dedupe(self):
        m = self._patch_common()
        m["discover"].return_value = [("sat", datetime.date(2026, 9, 5), _utc(2026, 9, 6))]
        m["ingested"].return_value = set()

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))

        call = m["record"].call_args_list[0]
        self.assertEqual(call.kwargs["day_of_week"], "sat")
        self.assertEqual(call.kwargs["data_date"], datetime.date(2026, 9, 5))
        self.assertEqual(call.kwargs["last_modified"], _utc(2026, 9, 6))
        # sha256 of the downloaded bytes, so a re-published file is detectable.
        self.assertEqual(len(call.kwargs["content_sha256"]), 64)


class TestResolveServices(unittest.TestCase):
    """--service selection: the mechanism that lets a new service be
    bootstrapped on a live deployment without re-loading data already
    serving traffic."""

    def test_no_selection_means_every_service(self):
        self.assertEqual(
            set(scheduler.resolve_services(None)), set(scheduler.SERVICES)
        )
        self.assertEqual(
            set(scheduler.resolve_services([])), set(scheduler.SERVICES)
        )

    def test_selection_is_limited_to_named_services(self):
        selected = scheduler.resolve_services(["gmrs", "ship"])
        self.assertEqual(set(selected), {"gmrs", "ship"})
        # The record-type maps must be the real ones, not copies/stubs.
        self.assertIs(selected["gmrs"], scheduler.SERVICES["gmrs"])

    def test_unknown_service_fails_loudly(self):
        """A typo must not silently ingest nothing and look like success."""
        with self.assertRaises(SystemExit) as ctx:
            scheduler.resolve_services(["gmrs", "typo"])
        self.assertIn("typo", str(ctx.exception))

    def test_all_new_personal_radio_services_are_registered(self):
        for name in ("gmrs", "aircraft", "ship"):
            self.assertIn(name, scheduler.SERVICES)


if __name__ == "__main__":
    unittest.main()


class TestAdvisoryLockPreventsOverlappingIngests(unittest.TestCase):
    """`change_events` has no unique constraint and differ compares against
    the CURRENTLY STORED row, so two interleaved ingests of the same day
    each emit a full set of events -- which the notifier turns into
    DUPLICATE USER ALERTS. Under a daily cron that was effectively
    impossible; polling every 15 minutes makes it plausible."""

    @patch("scheduler.ingest_advisory_lock")
    @patch("scheduler.discover_available_days")
    @patch("scheduler.psycopg.connect")
    def test_lock_held_elsewhere_makes_the_pass_a_clean_no_op(
        self, mock_connect, mock_discover, mock_lock
    ):
        mock_connect.return_value = MagicMock()
        mock_lock.side_effect = lambda conn: _fake_lock(False)

        result = scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))

        self.assertEqual(result, {})
        # It must not even look at what is available -- stepping aside is
        # the whole point, not doing the work and discarding it.
        mock_discover.assert_not_called()

    @patch("scheduler.psycopg.connect")
    def test_bootstrap_refuses_to_run_while_an_ingest_holds_the_lock(self, mock_connect):
        mock_connect.return_value = MagicMock()
        with patch("scheduler.ingest_advisory_lock", side_effect=lambda conn: _fake_lock(False)):
            # Loud failure, not a silent no-op: an operator typed this
            # command and must know it did nothing.
            with self.assertRaises(SystemExit):
                scheduler.bootstrap_all(services=["amateur"])


class TestCountsIntegrityCheck(unittest.TestCase):
    """Every FCC archive declares its own row count per file. Verified to
    match this project's ingestion exactly on production for two different
    services (amateur 2026-09-01 = 5,691; ship 2026-09-02 = 219), so a
    mismatch is real signal rather than noise."""

    def test_matching_counts_report_success(self):
        counts = parser.ArchiveCounts(rows={"HD.dat": 10, "EN.dat": 10}, created_at=None)
        status = scheduler._verify_against_counts(
            "amateur", "tue", datetime.date(2026, 9, 1), {"HD.dat": 10, "EN.dat": 10}, counts
        )
        self.assertEqual(status, "success")

    def test_mismatch_is_flagged_partial_not_failed(self):
        # Ingestion still happened; the run is marked so it shows up in
        # --status instead of being silently accepted.
        counts = parser.ArchiveCounts(rows={"HD.dat": 10}, created_at=None)
        status = scheduler._verify_against_counts(
            "amateur", "tue", datetime.date(2026, 9, 1), {"HD.dat": 7}, counts
        )
        self.assertEqual(status, "partial")

    def test_record_types_we_do_not_ingest_are_not_treated_as_missing(self):
        """FCC ships CO/SC/LA/SF rows this project deliberately skips.
        Comparing against those (or against the archive's "N total" line)
        would report a permanent false mismatch on every single file."""
        counts = parser.ArchiveCounts(
            rows={"HD.dat": 10, "CO.dat": 91, "SC.dat": 27, "LA.dat": 3}, created_at=None
        )
        status = scheduler._verify_against_counts(
            "amateur", "tue", datetime.date(2026, 9, 1), {"HD.dat": 10}, counts
        )
        self.assertEqual(status, "success")

    def test_absent_counts_member_is_not_an_error(self):
        status = scheduler._verify_against_counts(
            "amateur", "tue", datetime.date(2026, 9, 1), {"HD.dat": 10},
            parser.ArchiveCounts(rows={}, created_at=None),
        )
        self.assertEqual(status, "success")


class TestUndateableFileFallback(TestRunDailyJobCatchUp):
    """A file with no usable Last-Modified used to be skipped permanently,
    making it invisible forever. It is now dated from the archive's own
    `File Creation Date`, which matches Last-Modified exactly when both are
    present."""

    def test_counts_creation_date_dates_a_file_with_no_last_modified(self):
        m = self._patch_common()
        m["discover"].return_value = [("mon", None, None)]
        m["ingested"].return_value = set()
        # Published Tue 2026-09-01, so the Monday file holds 2026-08-31.
        m["counts"].return_value = parser.ArchiveCounts(
            rows={}, created_at=_utc(2026, 9, 1),
        )

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7), services=["amateur"])

        recorded = [c.kwargs["data_date"] for c in m["record"].call_args_list]
        self.assertEqual(recorded, [datetime.date(2026, 8, 31)])

    def test_undateable_file_already_ingested_is_not_reingested(self):
        m = self._patch_common()
        m["discover"].return_value = [("mon", None, None)]
        m["ingested"].return_value = {datetime.date(2026, 8, 31)}
        m["counts"].return_value = parser.ArchiveCounts(rows={}, created_at=_utc(2026, 9, 1))

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7), services=["amateur"])

        # Downloaded (it had to be, to be datable at all) but correctly
        # recognised as already loaded once its real date was known.
        m["download"].assert_called_once()
        m["record"].assert_not_called()
        m["ingest"].assert_not_called()

    def test_file_datable_by_neither_source_is_skipped_without_crashing(self):
        m = self._patch_common()
        m["discover"].return_value = [("mon", None, None)]
        m["ingested"].return_value = set()
        m["counts"].return_value = parser.ArchiveCounts(rows={}, created_at=None)

        scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7), services=["amateur"])

        m["record"].assert_not_called()
        m["refresh"].assert_not_called()


class TestOutstandingDates(unittest.TestCase):
    """Deciding what to HEAD is pure DB work -- that is what turns a poll
    from 35 requests into at most a handful."""

    def _conn_with(self, done):
        conn = MagicMock()
        return conn, patch("scheduler.ingested_data_dates", return_value=done)

    def test_fully_caught_up_service_has_nothing_outstanding(self):
        conn, p = self._conn_with(
            {datetime.date(2026, 9, 7) - datetime.timedelta(days=d) for d in range(1, 8)}
        )
        with p:
            result = scheduler.outstanding_dates(
                conn, {"amateur": {}}, datetime.date(2026, 9, 7), 7
            )
        self.assertEqual(result["amateur"], set())

    def test_missing_day_maps_back_to_its_weekday_file(self):
        # 2026-09-06 is a Sunday, so the missing day is served by l_am_sun.zip.
        done = {datetime.date(2026, 9, 7) - datetime.timedelta(days=d) for d in range(1, 8)}
        done.discard(datetime.date(2026, 9, 6))
        conn, p = self._conn_with(done)
        with p:
            result = scheduler.outstanding_dates(
                conn, {"amateur": {}}, datetime.date(2026, 9, 7), 7
            )
        self.assertEqual(result["amateur"], {"sun"})

    def test_todays_file_is_never_outstanding(self):
        """FCC does not publish day D's file until D+1, so treating today
        as missing would mean permanently HEADing a file that cannot exist
        yet."""
        done = {datetime.date(2026, 9, 7) - datetime.timedelta(days=d) for d in range(1, 8)}
        conn, p = self._conn_with(done)
        with p:
            result = scheduler.outstanding_dates(
                conn, {"amateur": {}}, datetime.date(2026, 9, 7), 7
            )
        self.assertNotIn(scheduler.DAYS_OF_WEEK[datetime.date(2026, 9, 7).weekday()],
                         result["amateur"])


class TestPollCycle(unittest.TestCase):
    def setUp(self):
        self.state = scheduler.PollState()

    def _patch(self, listing=None, missing=None, summary=None):
        patches = {
            "fetch": patch("scheduler.index_scraper.fetch_listing", return_value=listing),
            "connect": patch("scheduler.psycopg.connect", return_value=MagicMock()),
            "outstanding": patch("scheduler.outstanding_dates",
                                 return_value=missing or {"amateur": set()}),
            "job": patch("scheduler.run_daily_job", return_value=summary or {}),
        }
        started = {n: p.start() for n, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        return started

    def test_steady_state_poll_does_no_work(self):
        """Caught up + listing unchanged (304) == one request, zero bytes,
        no ingest. This is 95%+ of all polls."""
        m = self._patch(listing=None)  # None == 304 Not Modified
        # Pretend a full sweep just happened so this poll takes the fast path.
        self.state.last_full_sweep = datetime.datetime.now(datetime.timezone.utc)

        result = scheduler.run_poll_cycle(state=self.state, services=["amateur"])

        self.assertEqual(result, {})
        m["job"].assert_not_called()

    def test_outstanding_day_triggers_ingest_even_when_listing_is_unchanged(self):
        """The listing is a static file observed lagging real publication by
        over two hours, so a 304 must never be read as 'nothing to do' while
        we are still waiting on a day."""
        m = self._patch(listing=None, missing={"amateur": {"sun"}})
        self.state.last_full_sweep = datetime.datetime.now(datetime.timezone.utc)

        scheduler.run_poll_cycle(state=self.state, services=["amateur"])

        m["job"].assert_called_once()
        # Only the file backing the missing day is checked, not all seven.
        self.assertEqual(m["job"].call_args.kwargs["only_days"], {"amateur": {"sun"}})

    def test_full_sweep_checks_everything_and_ignores_the_conditional_header(self):
        m = self._patch(listing=None)
        self.state.last_full_sweep = None  # never swept -> due now

        scheduler.run_poll_cycle(state=self.state, services=["amateur"])

        self.assertIsNone(m["fetch"].call_args.kwargs["if_modified_since"])
        self.assertIsNone(m["job"].call_args.kwargs["only_days"])
        self.assertIsNotNone(self.state.last_full_sweep)

    def test_failure_backs_off_exponentially_and_recovers(self):
        m = self._patch(listing=None)
        self.state.last_full_sweep = datetime.datetime.now(datetime.timezone.utc)
        m["fetch"].side_effect = RuntimeError("FCC unreachable")

        scheduler.run_poll_cycle(state=self.state, services=["amateur"])
        self.assertEqual(self.state.consecutive_failures, 1)
        self.assertEqual(self.state.skip_polls_remaining, 2)

        # The next polls are skipped rather than hammering a server that is
        # already known to be down.
        scheduler.run_poll_cycle(state=self.state, services=["amateur"])
        self.assertEqual(self.state.skip_polls_remaining, 1)

        m["fetch"].side_effect = None
        scheduler.run_poll_cycle(state=self.state, services=["amateur"])  # consumes last skip
        scheduler.run_poll_cycle(state=self.state, services=["amateur"])  # succeeds
        self.assertEqual(self.state.consecutive_failures, 0)
        self.assertEqual(self.state.skip_polls_remaining, 0)

    def test_backoff_is_capped(self):
        state = scheduler.PollState()
        for _ in range(20):
            state.record_failure()
        self.assertEqual(state.skip_polls_remaining, scheduler.MAX_BACKOFF_POLLS)

    def test_a_poll_failure_never_propagates(self):
        """The scheduler thread must survive any FCC or database problem;
        an unhandled exception would kill polling until the next restart."""
        m = self._patch(listing=None)
        m["connect"].side_effect = RuntimeError("database gone")
        try:
            scheduler.run_poll_cycle(state=self.state, services=["amateur"])
        except Exception as exc:  # pragma: no cover - the assertion is the point
            self.fail(f"run_poll_cycle raised {exc!r} instead of backing off")
