"""Unit tests for the FCC directory-index scraper.

The fixture is a REAL listing captured from
https://data.fcc.gov/download/pub/uls/daily/ on 2026-09-08, trimmed to the
rows this project cares about. It is not synthesised, so it exercises the
actual markup FCC emits (uppercase tags, two-space separators, the
mc-icons header row) rather than a tidy approximation of it.
"""
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from index_scraper import (  # noqa: E402
    FCC_TZ,
    ListingEntry,
    entry_to_head_meta,
    http_date,
    parse_http_date,
    parse_listing,
)

FIXTURE = Path(__file__).parent / "fixtures" / "daily_index.html"


def _utc(y, m, d, hh, mm, ss):
    return datetime.datetime(y, m, d, hh, mm, ss, tzinfo=datetime.timezone.utc)


class TestParseRealListing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.entries = parse_listing(FIXTURE.read_text(encoding="utf-8"))

    def test_parses_every_real_row(self):
        # 6 file prefixes x 7 weekday files in the trimmed fixture.
        self.assertEqual(len(self.entries), 42)
        self.assertTrue(all(name.endswith(".zip") for name in self.entries))

    def test_header_and_markup_rows_are_not_mistaken_for_files(self):
        # The fixture keeps FCC's real <IMG>/<HR> header block and its
        # </pre></body> footer; a sloppy regex turns those into phantom
        # entries that would later be HEADed or downloaded.
        self.assertNotIn("blank.gif", self.entries)

    def test_timestamps_are_converted_from_eastern_to_utc(self):
        # Fixture row: l_am_tue.zip  2026-09-02 08:00:10  (Eastern, EDT).
        # Reading these as UTC would be four hours early -- enough to
        # resolve a file to the wrong data_date near a day boundary.
        entry = self.entries["l_am_tue.zip"]
        self.assertEqual(entry.modified, _utc(2026, 9, 2, 12, 0, 10))
        self.assertEqual(entry.size, 102319)

    def test_every_service_prefix_is_present(self):
        for prefix in ("l_am", "r_tow", "l_gm", "l_ac", "l_sh"):
            for dow in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                self.assertIn(f"{prefix}_{dow}.zip", self.entries)

    def test_empty_weekend_archives_are_reported_at_their_real_size(self):
        # 212 bytes == a zip holding only `counts` and no .dat members.
        # These are normal (weekends/holidays) and must not look like an
        # error, or a poller would retry them forever.
        self.assertEqual(self.entries["l_am_sun.zip"].size, 212)
        self.assertEqual(self.entries["l_am_mon.zip"].size, 212)

    def test_entry_adapts_to_head_daily_shape(self):
        meta = entry_to_head_meta(self.entries["l_am_tue.zip"])
        self.assertEqual(set(meta), {"last_modified", "size", "etag"})
        self.assertIsNotNone(meta["last_modified"].tzinfo)
        # FCC ignores If-None-Match and the listing publishes no per-file
        # ETag, so this is explicitly None rather than a fabricated value.
        self.assertIsNone(meta["etag"])


class TestTimezoneHandling(unittest.TestCase):
    def test_dst_transition_is_handled_by_real_timezone(self):
        """The offset MUST come from the tz database, not a constant.

        Every timestamp visible on FCC's server today is summer time, so a
        hardcoded -4 would pass every other test in this file and then
        silently shift every file by an hour at the November DST change.
        That cannot be checked against the live server until winter, so it
        is pinned here instead.
        """
        for local, expected_hour, label in [
            ("2026-01-15 08:00:00", 13, "EST (UTC-5)"),
            ("2026-07-15 08:00:00", 12, "EDT (UTC-4)"),
        ]:
            with self.subTest(label):
                html = f'<a href="x.zip">x.zip</a>  {local}   123'
                self.assertEqual(parse_listing(html)["x.zip"].modified.hour, expected_hour)

    def test_fcc_tz_is_a_named_zone_not_a_fixed_offset(self):
        # Guards against someone "simplifying" this to timezone(timedelta(hours=-4)).
        self.assertEqual(str(FCC_TZ), "America/New_York")


class TestTolerance(unittest.TestCase):
    """Parsing third-party HTML we do not control must degrade, not crash."""

    def test_malformed_rows_are_skipped_not_fatal(self):
        html = """
        <a href="good.zip">good.zip</a>  2026-09-02 08:00:10   100
        <a href="bad.zip">bad.zip</a>  not-a-timestamp   nope
        <a href="alsogood.zip">alsogood.zip</a>  2026-09-03 08:00:10   200
        """
        self.assertEqual(set(parse_listing(html)), {"good.zip", "alsogood.zip"})

    def test_unrecognisable_document_yields_nothing(self):
        # The caller treats this as "no listing" and falls back to per-file
        # HEADs, so an upstream redesign costs performance, not ingestion.
        self.assertEqual(parse_listing("<html><body>Service Unavailable</body></html>"), {})
        self.assertEqual(parse_listing(""), {})

    def test_non_zip_links_are_ignored(self):
        html = '<a href="index.html">index.html</a>  2026-09-02 08:00:10   100'
        self.assertEqual(parse_listing(html), {})


class TestHttpDateHelpers(unittest.TestCase):
    def test_http_date_round_trips(self):
        original = _utc(2026, 9, 8, 14, 15, 12)
        self.assertEqual(parse_http_date(http_date(original)), original)

    def test_parse_http_date_tolerates_garbage(self):
        self.assertIsNone(parse_http_date("nonsense"))
        self.assertIsNone(parse_http_date(""))

    def test_listing_entry_is_immutable(self):
        entry = ListingEntry("a.zip", _utc(2026, 1, 1, 0, 0, 0), 1)
        with self.assertRaises(Exception):
            entry.size = 2  # frozen dataclass


if __name__ == "__main__":
    unittest.main()
