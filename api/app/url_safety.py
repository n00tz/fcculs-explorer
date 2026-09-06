"""Shared SSRF guard for validating a webhook channel's URL at creation
time. Mirrors notifier/app/url_safety.py's policy (kept as a second,
independent copy since the api and notifier services don't share a Python
package) -- see that file for the full rationale. Blocks
loopback/private/link-local/multicast/reserved addresses, including cloud
metadata endpoints like 169.254.169.254 (covered by link-local), so a user
can't point a webhook/ntfy/matrix channel at the internal Podman network
or a host's metadata service.
"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}

# Test-only escape hatch: NOT read from .env, NOT wired into
# compose.yaml/Quadlets, and deliberately undocumented for operators --
# see notifier/app/url_safety.py for the matching flag and rationale.
# Never set this in a real deployment. Read at call time (not cached at
# import) so a test can flip it on/off after this module has already been
# imported by other application code.
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
    server-initiated outbound webhook request."""
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
