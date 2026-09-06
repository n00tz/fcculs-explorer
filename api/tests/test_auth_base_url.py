"""Regression tests for auth.resolve_base_url().

Covers two bugs:

1. Magic-link emails always contained settings.magic_link_base_url
   (default "http://localhost:8000", or whatever static PUBLIC_BASE_URL an
   operator configured) instead of the actual public hostname a browser
   used to reach the app -- e.g. a Cloudflare Tunnel hostname, which a
   self-hoster has no reason to also copy into .env and keep in sync.
   resolve_base_url() should derive the base URL from the incoming
   request's Host/X-Forwarded-* headers by default, only falling back to
   the static config value when trust_request_host is disabled or no Host
   header is present at all.
2. Host-header spoofing: since Caddy's Caddyfile doesn't strip/rewrite
   X-Forwarded-Host before proxying to the api service, any client could
   supply an arbitrary Host/X-Forwarded-Host and have it echoed straight
   into the emailed magic-link URL (and the session cookie's Secure-flag
   scheme decision). resolve_base_url() must validate the resolved
   scheme://host against settings.cors_allow_origins (the same trusted-
   origin allow-list already used for CORS) before trusting it, falling
   back to magic_link_base_url otherwise.
"""
import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")
os.environ.setdefault("FCCULS_MAGIC_LINK_BASE_URL", "http://testserver")

from app.config import settings
from app.routers.auth import resolve_base_url


def _fake_request(headers, url_scheme="http"):
    request = Mock()
    request.headers = headers
    request.url = Mock(scheme=url_scheme)
    return request


class TestResolveBaseUrl(unittest.TestCase):
    def setUp(self):
        self._orig_base_url = settings.magic_link_base_url
        self._orig_trust = settings.trust_request_host
        self._orig_cors_raw = settings.cors_allow_origins_raw
        # Default allow-list for tests that resolve to fcculs.example.net,
        # under both schemes exercised below.
        settings.cors_allow_origins_raw = "http://fcculs.example.net,https://fcculs.example.net"

    def tearDown(self):
        settings.magic_link_base_url = self._orig_base_url
        settings.trust_request_host = self._orig_trust
        settings.cors_allow_origins_raw = self._orig_cors_raw

    def test_uses_request_host_over_configured_base_url(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        request = _fake_request({"host": "fcculs.example.net"}, url_scheme="http")

        self.assertEqual(resolve_base_url(request), "http://fcculs.example.net")

    def test_prefers_x_forwarded_host_and_proto(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        request = _fake_request(
            {
                "host": "api:8000",
                "x-forwarded-host": "fcculs.example.net",
                "x-forwarded-proto": "https",
            },
            url_scheme="http",
        )

        self.assertEqual(resolve_base_url(request), "https://fcculs.example.net")

    def test_falls_back_to_cf_visitor_scheme(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        request = _fake_request(
            {"host": "fcculs.example.net", "cf-visitor": '{"scheme":"https"}'},
            url_scheme="http",
        )

        self.assertEqual(resolve_base_url(request), "https://fcculs.example.net")

    def test_falls_back_to_request_scheme_when_no_proto_headers(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        request = _fake_request({"host": "fcculs.example.net"}, url_scheme="https")

        self.assertEqual(resolve_base_url(request), "https://fcculs.example.net")

    def test_falls_back_to_configured_base_url_when_no_host_header(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        request = _fake_request({}, url_scheme="http")

        self.assertEqual(resolve_base_url(request), "http://localhost:8080")

    def test_uses_configured_base_url_when_trust_disabled(self):
        settings.trust_request_host = False
        settings.magic_link_base_url = "https://fcculs.configured.example"
        request = _fake_request({"host": "fcculs.example.net"}, url_scheme="http")

        self.assertEqual(resolve_base_url(request), "https://fcculs.configured.example")

    def test_spoofed_host_not_in_allowlist_falls_back(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        settings.cors_allow_origins_raw = "https://fcculs.example.net"
        request = _fake_request(
            {
                "host": "api:8000",
                "x-forwarded-host": "evil.attacker.example",
                "x-forwarded-proto": "https",
            },
            url_scheme="http",
        )

        # A spoofed X-Forwarded-Host that isn't a trusted CORS origin must
        # never be reflected into the emailed link/cookie scheme decision --
        # fall back to the static configured base URL instead.
        self.assertEqual(resolve_base_url(request), "http://localhost:8080")

    def test_allowlisted_host_resolves_correctly(self):
        settings.trust_request_host = True
        settings.magic_link_base_url = "http://localhost:8080"
        settings.cors_allow_origins_raw = "https://fcculs.example.net"
        request = _fake_request(
            {"host": "fcculs.example.net", "x-forwarded-proto": "https"},
            url_scheme="http",
        )

        self.assertEqual(resolve_base_url(request), "https://fcculs.example.net")


if __name__ == "__main__":
    unittest.main()
