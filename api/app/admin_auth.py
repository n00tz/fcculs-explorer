"""Superuser password for the hidden /admin panel.

By design there is no admin password *setting* anywhere (env var, .env,
database column) -- a fresh random password is generated in memory once per
API process start and printed to the process's own stdout (which is exactly
what `podman logs`/`journalctl --user -u fcculs-api` shows). This means the
only way to ever learn the current admin password is having access to the
running container's logs, matching the requested threat model ("a hidden
/admin panel where the superuser password can only be found by having
access to the container logs").

A side effect worth knowing operationally: the password rotates every time
the api container restarts (e.g. after `deploy/update.sh`), so an admin
session cookie is the only thing that persists sign-in across a login --
if you get logged out, check the current logs again for the current
password.
"""
import hmac
import logging
import secrets

from .security import hash_token

logger = logging.getLogger("fcculs.admin_auth")

_admin_password_hash: str | None = None


def init_admin_password() -> None:
    """Generate a fresh admin password and log it. Called once at API
    startup (see main.py's lifespan)."""
    global _admin_password_hash
    password = secrets.token_urlsafe(18)
    _admin_password_hash = hash_token(password)
    banner = "=" * 64
    logger.warning(
        "\n%s\n"
        "FCC ULS Explorer admin panel password (rotates on every restart):\n"
        "  %s\n"
        "Sign in at /admin. This password is never stored anywhere except\n"
        "this log line -- copy it now.\n"
        "%s",
        banner,
        password,
        banner,
    )


def verify_admin_password(candidate: str) -> bool:
    if _admin_password_hash is None:
        return False
    return hmac.compare_digest(hash_token(candidate), _admin_password_hash)
