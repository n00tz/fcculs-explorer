"""Regression tests for the Redis-backed rate limiter (app.ratelimit) as
applied to the unauthenticated read endpoints -- /api/search, /api/amateur
browse, /api/towers browse -- added because these run trigram/filter
queries against multi-million-row tables and are the app's easiest
DoS/cost-abuse surface once exposed to the internet, unlike
/api/auth/request-link and /api/admin/login which already had a limiter.

Mirrors the style of the other real-dependency tests in this suite
(test_admin_auth.py, test_mailer.py): plain unittest, asyncio.run() around
the async calls, no mocking of Redis itself -- app.ratelimit.enforce_rate_limit
talks to a REAL Redis instance (FCCULS_REDIS_URL, provided by
run_integration.sh's disposable Redis container), since a mocked Redis
client wouldn't actually prove the INCR/EXPIRE fixed-window logic works.
"""
import asyncio
import os
import sys
import unittest
import uuid

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")
os.environ.setdefault("FCCULS_MAGIC_LINK_BASE_URL", "http://testserver")

from fastapi import HTTPException

from app import ratelimit
from app.ratelimit import enforce_rate_limit


class TestEnforceRateLimit(unittest.TestCase):
    def setUp(self):
        # The Redis client is a lazily-created module-level singleton bound
        # to whichever asyncio event loop was running when it was first
        # used. Each test method below runs its own asyncio.run() (its own
        # fresh event loop). Dropping the reference directly (rather than
        # awaiting close_redis(), which would itself need an event loop and
        # would crash trying to close a connection bound to an already-
        # closed loop from a prior test) forces a fresh client -- and
        # therefore a fresh underlying connection bound to the *current*
        # test's loop -- to be created on next use.
        ratelimit._redis = None

    def _unique_key(self, label: str) -> str:
        # Unique per test run so tests never collide with each other or
        # with a prior run's leftover Redis keys.
        return f"test-{label}-{uuid.uuid4().hex}"

    def test_allows_requests_under_the_limit(self):
        key = self._unique_key("under-limit")

        async def run():
            for _ in range(3):
                await enforce_rate_limit(key, max_requests=3, window_seconds=60)

        asyncio.run(run())  # no exception raised == pass

    def test_raises_429_after_limit_exceeded(self):
        key = self._unique_key("over-limit")

        async def run():
            for _ in range(3):
                await enforce_rate_limit(key, max_requests=3, window_seconds=60)
            # The 4th call within the same window must be rejected.
            await enforce_rate_limit(key, max_requests=3, window_seconds=60)

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(run())
        self.assertEqual(ctx.exception.status_code, 429)

    def test_window_resets_after_expiry(self):
        key = self._unique_key("window-reset")

        async def run():
            for _ in range(2):
                await enforce_rate_limit(key, max_requests=2, window_seconds=1)
            with self.assertRaises(HTTPException):
                await enforce_rate_limit(key, max_requests=2, window_seconds=1)

            # Wait for the 1-second fixed window to expire in Redis (an
            # async sleep, staying on the same event loop/connection as the
            # calls above), then confirm the same key is allowed again --
            # proves this is a rolling/reset limiter, not a permanent ban
            # once tripped.
            await asyncio.sleep(1.5)
            await enforce_rate_limit(key, max_requests=2, window_seconds=1)

        asyncio.run(run())  # no exception raised on the final call == pass

    def test_different_keys_are_independent(self):
        key_a = self._unique_key("independent-a")
        key_b = self._unique_key("independent-b")

        async def run():
            await enforce_rate_limit(key_a, max_requests=1, window_seconds=60)
            # A different key must not be affected by key_a's usage.
            await enforce_rate_limit(key_b, max_requests=1, window_seconds=60)
            with self.assertRaises(HTTPException):
                await enforce_rate_limit(key_a, max_requests=1, window_seconds=60)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
