"""Auth primitives: magic-link token generation/hashing and signed session
cookies. No passwords are ever stored -- a user's identity is established
solely by proving control of their email inbox via a short-lived token.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

_serializer = URLSafeTimedSerializer(settings.session_secret, salt="fcculs-session")
_admin_serializer = URLSafeTimedSerializer(settings.session_secret, salt="fcculs-admin-session")



def generate_magic_link_token() -> tuple[str, str, datetime]:
    """Return (raw_token, token_hash, expires_at). Only the hash is persisted;
    the raw token is emailed to the user and never stored server-side, so a
    DB read can't leak a usable token (mirrors password-hash best practice)."""
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.magic_link_ttl_seconds)
    return raw_token, token_hash, expires_at


def hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"user_id": user_id})


def read_session_cookie(cookie_value: str) -> int | None:
    """Return the user_id encoded in a session cookie, or None if missing,
    tampered with, or expired."""
    try:
        data = _serializer.loads(cookie_value, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("user_id")


def create_admin_session_cookie() -> str:
    """Admin sessions carry no identity beyond "is the admin" -- there's only
    ever one superuser, authenticated by the process-generated password (see
    app.admin_auth), not by a user row. Signed with a distinct salt so an
    admin cookie can never be replayed as a regular user session or vice
    versa."""
    return _admin_serializer.dumps({"admin": True})


def read_admin_session_cookie(cookie_value: str) -> bool:
    """Return True if cookie_value is a valid, unexpired admin session."""
    try:
        data = _admin_serializer.loads(cookie_value, max_age=settings.admin_session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return False
    return bool(data.get("admin"))
