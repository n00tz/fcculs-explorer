import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")

from app.admin_auth import init_admin_password, verify_admin_password
from app.security import create_admin_session_cookie, read_admin_session_cookie


def test_admin_password_is_rejected_before_init():
    # A fresh process (or this test importing the module cold) has no
    # password hash set yet, so any candidate must be rejected -- this
    # guards against the panel ever being open with no password at all.
    import app.admin_auth as admin_auth_module

    admin_auth_module._admin_password_hash = None
    assert verify_admin_password("anything") is False


def test_admin_password_roundtrip_and_uniqueness(caplog):
    import re

    caplog.set_level("WARNING", logger="fcculs.admin_auth")
    init_admin_password()
    # Extract the password the same way an operator would: read it out of
    # the log line, nothing else -- there is no other source for it.
    logged = "\n".join(r.getMessage() for r in caplog.records)
    token_re = re.compile(r"[A-Za-z0-9_-]{20,}")
    candidates = [m for m in token_re.findall(logged) if m not in ("FCCULS", "admin")]
    assert candidates, f"no password-looking token found in log output: {logged!r}"
    password_line = candidates[0]
    assert verify_admin_password(password_line) is True
    assert verify_admin_password("wrong-password") is False

    first_password = password_line
    caplog.clear()
    init_admin_password()
    assert verify_admin_password(first_password) is False


def test_admin_session_cookie_roundtrip():
    cookie = create_admin_session_cookie()
    assert read_admin_session_cookie(cookie) is True


def test_admin_session_cookie_rejects_tampering():
    cookie = create_admin_session_cookie()
    tampered = cookie[:-1] + ("A" if cookie[-1] != "A" else "B")
    assert read_admin_session_cookie(tampered) is False


def test_admin_session_cookie_rejects_garbage():
    assert read_admin_session_cookie("not-a-real-cookie") is False
