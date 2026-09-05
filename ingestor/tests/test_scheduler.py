"""Unit tests for the scheduler's orchestration logic (mocks network/DB;
verifies the download -> extract -> match-filename -> ingest wiring, not
the ingestion logic itself which is already covered by test_parser/test_differ)."""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scheduler


class TestRunDailyJob(unittest.TestCase):
    @patch("scheduler.psycopg.connect")
    @patch("scheduler.ingest_file")
    @patch("scheduler.extract_zip")
    @patch("scheduler.download_daily")
    def test_downloads_and_ingests_every_service_and_record_type(
        self, mock_download_daily, mock_extract_zip, mock_ingest_file, mock_connect
    ):
        mock_download_daily.return_value = b"fake zip bytes"

        def fake_extract(content, dest_dir):
            # Simulate that every expected filename for either service exists.
            names = ["HD.dat", "EN.dat", "AM.dat", "HS.dat", "RA.dat", "CO.dat"]
            return [dest_dir / name for name in names]

        mock_extract_zip.side_effect = fake_extract
        mock_ingest_file.return_value = {"rows": 5, "changes": 1, "inserted": 0}
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn

        import datetime
        result = scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))  # Monday

        mock_download_daily.assert_any_call("amateur", "mon")
        mock_download_daily.assert_any_call("tower", "mon")
        self.assertEqual(mock_ingest_file.call_count, 4 + 3)  # amateur has 4 record types, tower has 3
        self.assertIn("amateur/HD.dat", result)
        self.assertIn("tower/RA.dat", result)
        mock_conn.commit.assert_called()  # from _refresh_materialized_views
        mock_conn.close.assert_called_once()

    @patch("scheduler.psycopg.connect")
    @patch("scheduler.ingest_file")
    @patch("scheduler.extract_zip")
    @patch("scheduler.download_daily")
    def test_missing_expected_file_is_skipped_not_fatal(
        self, mock_download_daily, mock_extract_zip, mock_ingest_file, mock_connect
    ):
        mock_download_daily.return_value = b"fake zip bytes"
        mock_extract_zip.return_value = []  # nothing extracted for either service
        mock_connect.return_value = MagicMock()

        import datetime
        result = scheduler.run_daily_job(run_date=datetime.date(2026, 9, 7))

        mock_ingest_file.assert_not_called()
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()
