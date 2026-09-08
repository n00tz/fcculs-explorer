"""Unit tests for the FCC .dat parser against real (small) fixture samples.
Run with: python3 -m unittest ingestor/tests/test_parser.py
(stdlib unittest only -- no pytest dependency required)
"""
import datetime
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser import parse_dat_file, RowFieldCountMismatch
import parser
import schemas

FIXTURES = Path(__file__).parent / "fixtures"


class TestParser(unittest.TestCase):
    def test_amat_hd_parses_expected_rows(self):
        rows = list(parse_dat_file(FIXTURES / "amat_HD.dat", schemas.AMAT_HD))
        self.assertEqual(len(rows), 5)
        first = rows[0]
        self.assertEqual(first["call_sign"], "KM4TYD")
        self.assertEqual(first["license_status"], "A")
        self.assertEqual(first["grant_date"], "08/29/2026")
        self.assertNotIn("record_type", first)

    def test_amat_en_parses_frn_and_entity_name(self):
        rows = list(parse_dat_file(FIXTURES / "amat_EN.dat", schemas.AMAT_EN))
        self.assertEqual(rows[0]["call_sign"], "KM4TYD")
        self.assertEqual(rows[0]["frn"], "0002204154")
        self.assertEqual(rows[0]["entity_name"], "BEAHM, DONALD E")

    def test_amat_am_parses_operator_class(self):
        rows = list(parse_dat_file(FIXTURES / "amat_AM.dat", schemas.AMAT_AM))
        self.assertEqual(rows[0]["callsign"], "KM4TYD")
        self.assertEqual(rows[0]["operator_class"], "T")

    def test_amat_hs_field_count(self):
        rows = list(parse_dat_file(FIXTURES / "amat_HS.dat", schemas.AMAT_HS))
        self.assertEqual(rows[0]["callsign"], "KM4TYD")
        self.assertEqual(rows[0]["code"], "LIREN")

    def test_tower_ra_content_indicator_and_registration_number_order(self):
        rows = list(parse_dat_file(FIXTURES / "tower_RA.dat", schemas.TOWER_RA))
        first = rows[0]
        self.assertEqual(first["content_indicator"], "REG")
        self.assertEqual(first["file_number"], "A1385250")
        self.assertEqual(first["registration_number"], "1334621")
        self.assertEqual(first["unique_system_identifier"], "2735132")
        self.assertEqual(first["structure_city"], "Columbia")
        self.assertEqual(first["height_of_structure"], "91.4")

    def test_tower_en_parses_entity_name_with_embedded_comma(self):
        rows = list(parse_dat_file(FIXTURES / "tower_EN.dat", schemas.TOWER_EN))
        self.assertEqual(rows[0]["entity_name"], "The Towers, LLC")
        self.assertEqual(rows[0]["frn"], "0033815929")

    def test_tower_co_parses_coordinates(self):
        rows = list(parse_dat_file(FIXTURES / "tower_CO.dat", schemas.TOWER_CO))
        first = rows[0]
        self.assertEqual(first["coordinate_type"], "T")
        self.assertEqual(first["latitude_direction"], "N")
        self.assertEqual(first["longitude_direction"], "W")

    def test_strict_mode_raises_on_field_count_mismatch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "bad_HD.dat"
            bad_file.write_text("HD|123|only|three|fields\n")
            with self.assertRaises(RowFieldCountMismatch):
                list(parse_dat_file(bad_file, schemas.AMAT_HD, strict=True))

    def test_non_strict_mode_tolerates_field_count_mismatch(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "short_HD.dat"
            bad_file.write_text("HD|123|only|three|fields\n")
            rows = list(parse_dat_file(bad_file, schemas.AMAT_HD, strict=False))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["unique_system_identifier"], "123")


class TestMultiLineAndDelimiterEdgeCases(unittest.TestCase):
    """Regressions for two hazards found in real FCC data on 2026-09-07."""

    def test_ship_sv_reassembles_records_split_across_physical_lines(self):
        """Ship SV descriptions contain raw newlines mid-field.

        In the real l_ship.zip, 389 of SV.dat's 1,068 physical lines are
        continuations of a previous record. Splitting on newlines (as the
        parser did before) turned 679 real records into 970 rows, 291 of
        them malformed.
        """
        path = FIXTURES / "ship_SV.dat"
        physical = [l for l in path.read_text(encoding="latin-1").splitlines() if l]
        self.assertGreater(len(physical), 3, "fixture must contain continuation lines")

        rows = list(parse_dat_file(path, schemas.SHIP_SV, strict=True))

        self.assertEqual(len(rows), 3)
        self.assertIn("\n", rows[0]["voyage_description"])
        self.assertTrue(rows[0]["voyage_description"].startswith("Vessel operates"))
        self.assertIn("inland waters", rows[0]["voyage_description"])

    def test_double_quotes_in_free_text_are_preserved_verbatim(self):
        """These files are raw pipe-delimited text with no quoting convention.

        Real SV descriptions contain double quotes; CSV-style parsing would
        treat a leading quote as syntax and silently rewrite the value.
        """
        rows = list(parse_dat_file(FIXTURES / "ship_SV.dat", schemas.SHIP_SV, strict=True))
        self.assertIn('"inland waters"', rows[0]["voyage_description"])

    def test_multi_row_descriptions_are_kept_as_separate_records(self):
        """FCC splits one long description across sequence-numbered rows
        sharing a unique_system_identifier; both must survive, since the
        table's natural key is (identifier, voyage_number)."""
        rows = list(parse_dat_file(FIXTURES / "ship_SV.dat", schemas.SHIP_SV, strict=True))
        same_vessel = [r for r in rows if r["unique_system_identifier"] == "1234"]
        self.assertEqual(len(same_vessel), 2)
        self.assertEqual([r["voyage_number"] for r in same_vessel], ["1", "2"])

    def test_unescaped_delimiter_in_free_text_is_tolerated_not_fatal(self):
        """FCC does not escape '|', so a literal pipe typed into a free-text
        field yields extra columns (17 such rows across 5.6M in the current
        dumps, e.g. an attention line reading
        'Director of Safety | Charter Ops Manager').

        Strict mode must reject it; lenient mode (used by the ingestor) must
        tolerate it so one bad row can't fail an entire nightly ingest.
        """
        bad = FIXTURES / "ship_SV_unescaped_pipe.dat"
        bad.write_text(
            "SV|9999|0009999999||WDA9999|1|Ops | Safety manager notes\n",
            encoding="latin-1",
        )
        try:
            with self.assertRaises(RowFieldCountMismatch):
                list(parse_dat_file(bad, schemas.SHIP_SV, strict=True))

            rows = list(parse_dat_file(bad, schemas.SHIP_SV, strict=False))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["call_sign"], "WDA9999")
        finally:
            bad.unlink()

    def test_record_type_is_taken_from_the_last_filename_segment(self):
        """Fixtures are named '<service>_<RECORD>.dat' while FCC ships
        '<RECORD>.dat'; both must resolve to the same record type, or
        continuation detection silently stops working."""
        rows = list(parse_dat_file(FIXTURES / "ship_SV.dat", schemas.SHIP_SV, strict=True))
        self.assertEqual(len(rows), 3)

    def test_explicit_record_type_overrides_the_filename(self):
        rows = list(parse_dat_file(
            FIXTURES / "ship_SV.dat", schemas.SHIP_SV, strict=True, record_type="SV",
        ))
        self.assertEqual(len(rows), 3)


class TestSharedULSSchemas(unittest.TestCase):
    """HD/EN/HS are generic ULS records, identical across every service."""

    def test_amateur_aliases_point_at_the_shared_definitions(self):
        self.assertIs(schemas.AMAT_HD, schemas.ULS_HD)
        self.assertIs(schemas.AMAT_EN, schemas.ULS_EN)
        self.assertIs(schemas.AMAT_HS, schemas.ULS_HS)

    def test_every_service_uses_the_same_hd_en_hs_layout(self):
        for service in ("amateur", "gmrs", "aircraft", "ship"):
            for dat in ("HD.dat", "EN.dat", "HS.dat"):
                with self.subTest(service=service, record=dat):
                    self.assertIs(
                        schemas.SERVICES[service][dat]["schema"],
                        getattr(schemas, "ULS_" + dat[:2]),
                    )

    def test_new_record_schemas_have_the_field_counts_seen_in_real_files(self):
        # Counts confirmed by strict-parsing every row of the real complete
        # dumps on 2026-09-07 (152,632 AC / 402,276 SH / 131,815 SR /
        # 679 SV / 368 SE rows, zero mismatches).
        self.assertEqual(len(schemas.AIRCR_AC), 10)
        self.assertEqual(len(schemas.SHIP_SH), 27)
        self.assertEqual(len(schemas.SHIP_SR), 21)
        self.assertEqual(len(schemas.SHIP_SV), 7)
        self.assertEqual(len(schemas.SHIP_SE), 42)

    def test_gmrs_has_no_service_specific_record(self):
        """l_gmrs.zip ships only HD/EN/HS (plus CO/LA/SC, not ingested)."""
        self.assertEqual(set(schemas.SERVICES["gmrs"]), {"HD.dat", "EN.dat", "HS.dat"})

    def test_record_type_is_derived_for_every_registered_record(self):
        for service, record_types in schemas.SERVICES.items():
            for filename, meta in record_types.items():
                with self.subTest(service=service, record=filename):
                    self.assertEqual(meta["record_type"], filename.split(".")[0].upper())


if __name__ == "__main__":
    unittest.main()


class TestParseCounts(unittest.TestCase):
    """Every FCC archive carries a `counts` member declaring its own row
    count per file. The strings below are REAL, captured verbatim from
    l_am_tue.zip / l_sh_wed.zip / l_am_sun.zip on 2026-09-08 -- including
    the CRLF line endings and the padded single-digit day, both of which a
    hand-written approximation would quietly omit.
    """

    AMATEUR = (
        "File Creation Date: Wed Sep  2 08:00:10 EDT 2026\r\n"
        "   819 /home/pubacc/scripts/licdayzipdata/AM.dat\r\n"
        "    91 /home/pubacc/scripts/licdayzipdata/CO.dat\r\n"
        "   819 /home/pubacc/scripts/licdayzipdata/EN.dat\r\n"
        "   819 /home/pubacc/scripts/licdayzipdata/HD.dat\r\n"
        "  3234 /home/pubacc/scripts/licdayzipdata/HS.dat\r\n"
        "     3 /home/pubacc/scripts/licdayzipdata/LA.dat\r\n"
        "    27 /home/pubacc/scripts/licdayzipdata/SC.dat\r\n"
        "  5812 total\r\n"
    )
    # A weekend/holiday archive: 212 bytes, `counts` only, no .dat at all.
    EMPTY = "File Creation Date: Mon Sep  7 08:00:09 EDT 2026\r\n"

    def test_row_counts_are_keyed_by_bare_filename(self):
        counts = parser.parse_counts(self.AMATEUR)
        self.assertEqual(counts.rows["HD.dat"], 819)
        self.assertEqual(counts.rows["HS.dat"], 3234)
        # Keyed by name, not by FCC's internal absolute path, so it lines up
        # with what extract_zip() produces.
        self.assertNotIn("/home/pubacc/scripts/licdayzipdata/HD.dat", counts.rows)

    def test_amateur_ingested_types_sum_to_the_value_verified_on_production(self):
        # 819 + 819 + 819 + 3234 = 5691, which matched ingest_runs
        # .rows_ingested exactly for amateur 2026-09-01.
        counts = parser.parse_counts(self.AMATEUR)
        ingested = ["AM.dat", "EN.dat", "HD.dat", "HS.dat"]
        self.assertEqual(sum(counts.rows[f] for f in ingested), 5691)

    def test_total_line_is_not_captured_as_a_file(self):
        """FCC's trailing "N total" counts record types this project does
        not ingest, so treating it as a file would produce a permanent
        false mismatch on every archive."""
        counts = parser.parse_counts(self.AMATEUR)
        self.assertNotIn("total", counts.rows)
        self.assertEqual(len(counts.rows), 7)

    def test_creation_date_is_converted_from_eastern_to_utc(self):
        # "Wed Sep  2 08:00:10 EDT 2026" -> 12:00:10Z, which matches that
        # archive's Last-Modified header exactly. That equivalence is why
        # this can date a file whose Last-Modified is missing.
        counts = parser.parse_counts(self.AMATEUR)
        self.assertEqual(
            counts.created_at,
            datetime.datetime(2026, 9, 2, 12, 0, 10, tzinfo=datetime.timezone.utc),
        )

    def test_winter_archive_uses_est_not_a_hardcoded_offset(self):
        counts = parser.parse_counts("File Creation Date: Thu Jan 15 08:00:00 EST 2026\r\n")
        self.assertEqual(counts.created_at.hour, 13)  # UTC-5

    def test_empty_weekend_archive_parses_with_no_rows(self):
        counts = parser.parse_counts(self.EMPTY)
        self.assertEqual(counts.rows, {})
        self.assertIsNotNone(counts.created_at)

    def test_unparseable_counts_is_tolerated(self):
        # Metadata failing to parse must never block an otherwise-valid
        # ingest; callers read this as "no integrity oracle available".
        counts = parser.parse_counts("something entirely unexpected")
        self.assertEqual(counts.rows, {})
        self.assertIsNone(counts.created_at)

    def test_unparseable_creation_date_does_not_lose_the_row_counts(self):
        counts = parser.parse_counts(
            "File Creation Date: sometime last Tuesday\r\n"
            "   819 /home/pubacc/scripts/licdayzipdata/HD.dat\r\n"
        )
        self.assertIsNone(counts.created_at)
        self.assertEqual(counts.rows["HD.dat"], 819)
