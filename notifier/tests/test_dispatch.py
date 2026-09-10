"""Unit tests for the dispatch loop's heartbeat recording (no real DB/Redis
-- match_and_record, the queue, and the DB connection are all mocked)."""
import unittest
from unittest.mock import MagicMock, patch

import sys
sys.path.insert(0, "/app")

from app import dispatch


class TestDispatchHeartbeat(unittest.TestCase):
    def _patch(self, new_delivery_ids=None):
        patches = {
            "get_connection": patch("app.dispatch.get_connection", return_value=MagicMock()),
            "match_and_record": patch("app.dispatch.match_and_record",
                                       return_value=new_delivery_ids or []),
            "redis": patch("app.dispatch.Redis.from_url", return_value=MagicMock()),
            "queue": patch("app.dispatch.Queue"),
            "heartbeat": patch("app.dispatch.record_heartbeat"),
        }
        started = {n: p.start() for n, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)
        return started

    def test_heartbeat_recorded_when_nothing_is_enqueued(self):
        """The common steady-state case: nothing new to send. The heartbeat
        must still be recorded so a stale row can only mean the loop died,
        not that this cycle happened to find nothing."""
        m = self._patch(new_delivery_ids=[])

        result = dispatch.run_once()

        self.assertEqual(result, 0)
        m["heartbeat"].assert_called_once()
        self.assertEqual(m["heartbeat"].call_args.args[1], "notifier-dispatch")
        self.assertEqual(m["heartbeat"].call_args.kwargs["detail"], {"enqueued": 0})

    def test_heartbeat_recorded_when_deliveries_are_enqueued(self):
        m = self._patch(new_delivery_ids=[1, 2, 3])

        result = dispatch.run_once()

        self.assertEqual(result, 3)
        m["heartbeat"].assert_called_once()
        self.assertEqual(m["heartbeat"].call_args.kwargs["detail"], {"enqueued": 3})

    def test_a_failing_heartbeat_write_does_not_break_dispatch(self):
        """Heartbeat recording is best-effort observability; it must never
        take down the actual dispatch cycle it is instrumenting."""
        m = self._patch(new_delivery_ids=[1])
        m["heartbeat"].side_effect = RuntimeError("heartbeat db down")

        result = dispatch.run_once()

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
