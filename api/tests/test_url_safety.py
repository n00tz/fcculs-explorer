import os
import sys
from unittest.mock import patch

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")

from app.url_safety import UnsafeUrlError, assert_safe_webhook_url


def _addrinfo(ip: str):
    return [(None, None, None, None, (ip, 0))]


def test_rejects_missing_url():
    try:
        assert_safe_webhook_url("")
        assert False, "expected UnsafeUrlError"
    except UnsafeUrlError:
        pass


def test_rejects_non_http_scheme():
    try:
        assert_safe_webhook_url("file:///etc/passwd")
        assert False, "expected UnsafeUrlError"
    except UnsafeUrlError:
        pass


def test_rejects_loopback():
    with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
        try:
            assert_safe_webhook_url("http://localhost/hook")
            assert False, "expected UnsafeUrlError"
        except UnsafeUrlError:
            pass


def test_rejects_metadata_address():
    with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("169.254.169.254")):
        try:
            assert_safe_webhook_url("http://metadata.internal/")
            assert False, "expected UnsafeUrlError"
        except UnsafeUrlError:
            pass


def test_allows_public_address():
    with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("93.184.216.34")):
        assert_safe_webhook_url("https://example.com/hook")  # should not raise


def test_testing_escape_hatch_bypasses_private_range_check():
    # See notifier/tests/test_url_safety.py for the rationale; this flag
    # is off by default and not wired into any real deployment path.
    with patch("app.url_safety.socket.getaddrinfo", return_value=_addrinfo("127.0.0.1")):
        try:
            assert_safe_webhook_url("http://localhost/hook")
            assert False, "expected UnsafeUrlError when flag is unset"
        except UnsafeUrlError:
            pass
        with patch.dict("os.environ", {"FCCULS_ALLOW_PRIVATE_WEBHOOK_TARGETS_FOR_TESTING": "1"}):
            assert_safe_webhook_url("http://localhost/hook")  # should not raise
