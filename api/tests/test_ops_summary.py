"""Unit tests for the admin ops-summary heartbeat-staleness classifier.

Pure logic, no DB -- the aggregation query itself (real rows from
service_heartbeats/ingest_runs/etc.) is exercised against a real Postgres
in tests/integration_test.py, matching how the rest of the /api/admin/*
endpoints are tested (see that file's "hidden /admin panel" block).
"""
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")

from app.routers.admin import _heartbeat_state  # noqa: E402


def test_none_age_is_unknown_not_down():
    # A loop that has never recorded a heartbeat yet (fresh migration,
    # first deploy) is a different condition than one that stopped -- it
    # must not be reported as "down".
    assert _heartbeat_state(None, ok_seconds=100, stale_seconds=200) == "unknown"


def test_age_within_ok_window_is_ok():
    assert _heartbeat_state(50, ok_seconds=100, stale_seconds=200) == "ok"
    assert _heartbeat_state(100, ok_seconds=100, stale_seconds=200) == "ok"  # boundary is inclusive


def test_age_past_ok_but_within_stale_window_is_stale():
    assert _heartbeat_state(101, ok_seconds=100, stale_seconds=200) == "stale"
    assert _heartbeat_state(200, ok_seconds=100, stale_seconds=200) == "stale"  # boundary is inclusive


def test_age_past_stale_window_is_down():
    assert _heartbeat_state(201, ok_seconds=100, stale_seconds=200) == "down"
