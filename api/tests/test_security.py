import os
import sys
import time

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")

from app.security import (
    create_session_cookie,
    generate_magic_link_token,
    hash_token,
    read_session_cookie,
)


def test_magic_link_token_is_random_and_hash_is_deterministic():
    raw1, hash1, _ = generate_magic_link_token()
    raw2, hash2, _ = generate_magic_link_token()
    assert raw1 != raw2
    assert hash1 != hash2
    assert hash_token(raw1) == hash1


def test_session_cookie_roundtrip():
    cookie = create_session_cookie(user_id=42)
    assert read_session_cookie(cookie) == 42


def test_session_cookie_rejects_tampering():
    cookie = create_session_cookie(user_id=42)
    # Flip a character in the payload segment (before the first ".") rather
    # than the very last character of the signature: the trailing base64
    # character of an HMAC digest sometimes encodes unused bits, so it can
    # occasionally decode to the same bytes when altered, making that
    # specific position an unreliable place to test tamper-detection (see
    # the identical fix applied to test_admin_auth.py's equivalent test).
    payload, _, rest = cookie.partition(".")
    tampered_payload = payload[:-1] + ("A" if payload[-1] != "A" else "B")
    tampered = f"{tampered_payload}.{rest}"
    assert read_session_cookie(tampered) is None


def test_session_cookie_rejects_garbage():
    assert read_session_cookie("not-a-real-cookie") is None
