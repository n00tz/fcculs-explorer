"""Real end-to-end smoke test for send_magic_link_email() against a live
(disposable) SMTP listener that does NOT support/advertise AUTH -- the
same situation as a real production relay that never advertises AUTH.
Confirms the fix actually completes a real send with no exception, not
just that aiosmtplib was called with the right kwargs (that's covered by
the mocked unit tests in tests/test_mailer.py).

send_magic_link_email() intentionally swallows/logs SMTP exceptions rather
than raising them (so the caller always returns a generic response), so
this script installs a logging handler to detect a logged failure instead
of relying on an exception propagating out.
"""
import asyncio
import logging
import os
import sys

sys.path.insert(0, "/app")
os.environ.setdefault("FCCULS_SESSION_SECRET", "test-secret")
os.environ.setdefault("FCCULS_MAGIC_LINK_BASE_URL", "http://testserver")

from app import mailer
from app.config import settings


class _CaptureErrors(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


async def main():
    capture = _CaptureErrors()
    mailer.logger.addHandler(capture)

    # Reproduce the exact bug condition: FCCULS_SMTP_USER="" (empty string,
    # not unset), as rendered by the Quadlet units' Environment= lines.
    settings.smtp_user = ""
    settings.smtp_password = ""
    settings.smtp_host = os.environ["FCCULS_SMTP_HOST"]
    settings.smtp_port = int(os.environ["FCCULS_SMTP_PORT"])
    settings.smtp_use_tls = False

    await mailer.send_magic_link_email(
        "realtest@example.com", "http://testserver/auth/callback?token=REALTOKEN123"
    )

    if capture.records:
        print("FAIL: send_magic_link_email logged an error:")
        for r in capture.records:
            print(r)
        raise SystemExit(1)

    print("PASS: real send against non-AUTH SMTP listener completed with no logged error")


if __name__ == "__main__":
    asyncio.run(main())

