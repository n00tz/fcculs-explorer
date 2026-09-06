import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from differ import diff_rows


class TestDiffer(unittest.TestCase):
    def test_no_diff_for_new_record(self):
        self.assertEqual(diff_rows(None, {"call_sign": "KM4TYD", "status": "A"}), [])

    def test_no_diff_when_identical(self):
        old = {"call_sign": "KM4TYD", "status": "A"}
        new = {"call_sign": "KM4TYD", "status": "A"}
        self.assertEqual(diff_rows(old, new), [])

    def test_detects_single_field_change(self):
        old = {"call_sign": "KM4TYD", "status": "A", "city": "GREAT BEND"}
        new = {"call_sign": "KM4TYD", "status": "E", "city": "GREAT BEND"}
        changes = diff_rows(old, new)
        self.assertEqual(changes, [("status", "A", "E")])

    def test_none_and_empty_string_are_equivalent(self):
        old = {"fax": None}
        new = {"fax": ""}
        self.assertEqual(diff_rows(old, new), [])

    def test_detects_multiple_field_changes(self):
        old = {"status": "A", "city": "GREAT BEND", "expired_date": "01/01/2030"}
        new = {"status": "E", "city": "WICHITA", "expired_date": "01/01/2030"}
        changes = diff_rows(old, new)
        self.assertEqual(set(changes), {("status", "A", "E"), ("city", "GREAT BEND", "WICHITA")})


if __name__ == "__main__":
    unittest.main()
