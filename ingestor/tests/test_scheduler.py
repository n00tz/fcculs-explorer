"""Unit tests for the scheduler's catch-up orchestration and for resolving
which real calendar date each weekday-named FCC daily file actually holds.

Mocks network/DB; verifies the HEAD -> resolve-date -> skip-already-ingested
-> download -> ingest -> record wiring, not the ingestion logic itself (which
is already covered by test_parser/test_differ).
"""
import datetime
import sys
import unittest
from email.utils import format_datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import downloader
import scheduler


def _utc(y, m, d, hh=12, mm=0):
    return datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.timezone.utc)


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
    def test_undateable_and_failing_files_are_skipped_not_fatal(self, mock_head):
        def fake_head(service, dow):
            if dow == "wed":
                raise RuntimeError("connection reset")
            if dow == "thu":
                return {"last_modified": None, "size": None, "etag": None}
            return {"last_modified": _utc(2026, 9, 7), "size": 1, "etag": None}

        mock_head.side_effect = fake_head
        result = scheduler.discover_available_days("amateur")

        got_days = {dow for dow, _, _ in result}
        self.assertNotIn("wed", got_days)  # HEAD failed
        self.assertNotIn("thu", got_days)  # no Last-Modified to date it by
        self.assertEqual(len(result), 5)


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
