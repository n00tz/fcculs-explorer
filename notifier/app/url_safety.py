"""Shared SSRF guard for anything that sends an HTTP request to a
user-supplied URL (webhook channels, ntfy, and the homeserver a Matrix
channel points at). Blocks requests to loopback/private/link-local/
multicast/reserved addresses -- including cloud metadata endpoints like
169.254.169.254, which fall under link-local -- so a malicious watch
channel can't be used to probe or attack services on the internal Podman
network (postgres/redis/api) or a host's cloud metadata service.

Kept intentionally small and dependency-free so it's easy to keep this
file and the API service's copy (api/app/url_safety.py) in sync; both
implement the same policy independently since the api and notifier
services don't share a Python package today.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Test-only escape hatch: NOT read from .env, NOT wired into
# compose.yaml/Quadlets, and deliberately undocumented for operators --
# it exists solely so this service's own local integration test (which
# delivers a real webhook to a mock HTTP server on loopback, inside the
# same disposable test container) can exercise the full
# match->enqueue->send pipeline without the SSRF guard blocking its own
# test fixture. Never set this in a real deployment. Read at call time
# (not cached at import) so a test can flip it on/off after this module
# has already been imported by other application code.
def _allow_private_targets_for_testing() -> bool:
    return os.environ.get("FCCULS_ALLOW_PRIVATE_WEBHOOK_TARGETS_FOR_TESTING") == "1"


class UnsafeUrlError(Exception):
    """Raised when a URL fails the SSRF safety check."""


def _is_unsafe_ip(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def assert_safe_webhook_url(url: str) -> None:
    """Raise UnsafeUrlError if `url` is not a safe target for a
    server-initiated outbound webhook request. Re-resolves the hostname
    every call (rather than caching), since DNS can change between when a
    channel is created and when a notification is actually sent
    (DNS-rebinding defense-in-depth)."""
    if not url:
        raise UnsafeUrlError("missing URL")

    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"scheme must be one of {sorted(ALLOWED_SCHEMES)}, got {parsed.scheme!r}")
    if not parsed.hostname:
        raise UnsafeUrlError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(parsed.hostname, None)
    except OSError as exc:
        # socket.gaierror (the common case) is a subclass of OSError;
        # catching OSError broadly also covers other resolution failures.
        raise UnsafeUrlError(f"could not resolve hostname {parsed.hostname!r}: {exc}") from exc

    resolved_ips = {info[4][0] for info in addrinfo}
    if _allow_private_targets_for_testing():
        return
    for ip_str in resolved_ips:
        if _is_unsafe_ip(ip_str):
            raise UnsafeUrlError(
                f"hostname {parsed.hostname!r} resolves to disallowed address {ip_str} "
                "(loopback/private/link-local/multicast/reserved ranges are blocked)"
            )
