"""Unit tests for the FCC .dat parser against real (small) fixture samples.
Run with: python3 -m unittest ingestor/tests/test_parser.py
(stdlib unittest only -- no pytest dependency required)
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parser import parse_dat_file, RowFieldCountMismatch
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


if __name__ == "__main__":
    unittest.main()
