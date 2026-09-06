"""Regression test for send_magic_link_email()'s SMTP-auth-kwargs guard.

Covers the bug where an empty-string (not None) FCCULS_SMTP_USER -- as
rendered by the Quadlet units' Environment=, which always sets the var to
a real (possibly empty) string rather than omitting it -- caused
aiosmtplib.send() to be called with username="" instead of no username at
all. aiosmtplib treats any non-None username as "please AUTH", so it would
attempt AUTH against relays that don't support/advertise it and fail with
"The SMTP AUTH extension is not supported by this server."
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")
os.environ.setdefault("FCCULS_MAGIC_LINK_BASE_URL", "http://testserver")

from app import mailer
from app.config import settings


class TestSendMagicLinkEmailAuthGuard(unittest.TestCase):
    def setUp(self):
        # Snapshot settings so each test can mutate them without bleeding
        # into other tests (settings is a module-level singleton).
        self._orig_user = settings.smtp_user
        self._orig_password = settings.smtp_password

    def tearDown(self):
        settings.smtp_user = self._orig_user
        settings.smtp_password = self._orig_password

    def test_no_username_kwarg_when_smtp_user_is_empty_string(self):
        # Reproduces the exact failure mode: FCCULS_SMTP_USER="" (empty
        # string, not unset) as rendered by the Quadlet Environment= lines.
        settings.smtp_user = ""
        settings.smtp_password = ""

        with patch("app.mailer.aiosmtplib.send") as mock_send:
            asyncio.run(mailer.send_magic_link_email("someone@example.com", "http://x/callback?token=abc"))

            mock_send.assert_called_once()
            _, kwargs = mock_send.call_args
            self.assertNotIn("username", kwargs)
            self.assertNotIn("password", kwargs)

    def test_no_username_kwarg_when_smtp_user_is_none(self):
        settings.smtp_user = None
        settings.smtp_password = None

        with patch("app.mailer.aiosmtplib.send") as mock_send:
            asyncio.run(mailer.send_magic_link_email("someone@example.com", "http://x/callback?token=abc"))

            _, kwargs = mock_send.call_args
            self.assertNotIn("username", kwargs)
            self.assertNotIn("password", kwargs)

    def test_username_and_password_passed_when_smtp_user_configured(self):
        settings.smtp_user = "relay-user"
        settings.smtp_password = "relay-pass"

        with patch("app.mailer.aiosmtplib.send") as mock_send:
            asyncio.run(mailer.send_magic_link_email("someone@example.com", "http://x/callback?token=abc"))

            _, kwargs = mock_send.call_args
            self.assertEqual(kwargs["username"], "relay-user")
            self.assertEqual(kwargs["password"], "relay-pass")

    def test_password_defaults_to_empty_string_when_user_set_but_password_none(self):
        settings.smtp_user = "relay-user"
        settings.smtp_password = None

        with patch("app.mailer.aiosmtplib.send") as mock_send:
            asyncio.run(mailer.send_magic_link_email("someone@example.com", "http://x/callback?token=abc"))

            _, kwargs = mock_send.call_args
            self.assertEqual(kwargs["username"], "relay-user")
            self.assertEqual(kwargs["password"], "")


if __name__ == "__main__":
    unittest.main()
