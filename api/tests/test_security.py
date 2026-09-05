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
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
    assert read_session_cookie(tampered) is None


def test_session_cookie_rejects_garbage():
    assert read_session_cookie("not-a-real-cookie") is None
