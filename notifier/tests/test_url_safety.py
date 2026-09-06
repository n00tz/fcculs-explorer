"""Unit tests for the webhook SSRF guard (notifier/app/url_safety.py).
DNS resolution is mocked so these tests are deterministic and don't depend
on network access from wherever they run."""
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/app")

from app.url_safety import UnsafeUrlError, assert_safe_webhook_url


def _addrinfo(ip: str):
    # Minimal shape of what socket.getaddrinfo returns: a list of tuples
    # whose 5th element (index 4) is the (address, port) sockaddr.
    return [(None, None, None, None, (ip, 0))]


class TestAssertSafeWebhookUrl(unittest.TestCase):
    def test_rejects_missing_url(self):
        with self.assertRaises(UnsafeUrlError):
            assert_safe_webhook_url("")

    def test_rejects_non_http_scheme(self):
        with self.assertRaises(UnsafeUrlError):
            assert_safe_webhook_url("file:///etc/passwd")

    def test_rejects_url_with_no_hostname(self):
        with self.assertRaises(UnsafeUrlError):
            assert_safe_webhook_url("https://")

    def test_rejects_unresolvable_hostname(self):
        with patch("app.url_safety.socket.getaddrinfo", side_effect=OSError("nope")):
            with self.assertRaises(UnsafeUrlError):
                assert_safe_webhook_url("https://does-not-resolve.example")

    def test_rejects_loopback(self):
        with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            with self.assertRaises(UnsafeUrlError):
                assert_safe_webhook_url("http://localhost/hook")

    def test_rejects_private_range(self):
        with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("10.0.0.5")):
            with self.assertRaises(UnsafeUrlError):
                assert_safe_webhook_url("http://internal-service/hook")

    def test_rejects_link_local_metadata_address(self):
        with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
            with self.assertRaises(UnsafeUrlError):
                assert_safe_webhook_url("http://metadata.internal/latest")

    def test_rejects_podman_internal_service_name(self):
        # e.g. a watch pointed at http://postgres:5432 or http://api:8000 --
        # these resolve, on the real internal network, to a private-range
        # container IP, which is exactly what this guard should catch.
        with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("10.89.0.5")):
            with self.assertRaises(UnsafeUrlError):
                assert_safe_webhook_url("http://postgres:5432/")

    def test_allows_public_address(self):
        with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
            assert_safe_webhook_url("https://example.com/hook")  # should not raise

    def test_testing_escape_hatch_bypasses_private_range_check(self):
        # FCCULS_ALLOW_PRIVATE_WEBHOOK_TARGETS_FOR_TESTING exists solely
        # for this service's own integration test (see tests/integration_test.py),
        # never set by any real deployment path (compose.yaml/Quadlets/.env.example
        # don't reference it). Confirm it actually bypasses the check, and that
        # it's off by default.
        with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
            with self.assertRaises(UnsafeUrlError):
                assert_safe_webhook_url("http://localhost/hook")  # off by default
            with patch.dict(
                "os.environ", {"FCCULS_ALLOW_PRIVATE_WEBHOOK_TARGETS_FOR_TESTING": "1"}
            ):
                assert_safe_webhook_url("http://localhost/hook")  # should not raise


if __name__ == "__main__":
    unittest.main()
