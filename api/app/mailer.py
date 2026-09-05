"""Outbound email via a BYO SMTP relay (no third-party API dependency)."""
import logging

import aiosmtplib
from email.message import EmailMessage

from .config import settings

logger = logging.getLogger(__name__)


async def send_magic_link_email(to_address: str, link_url: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = to_address
    message["Subject"] = "Your FCC ULS Explorer sign-in link"
    message.set_content(
        "Click the link below to sign in to FCC ULS Explorer. "
        f"This link expires in {settings.magic_link_ttl_seconds // 60} minutes "
        "and can only be used once.\n\n"
        f"{link_url}\n\n"
        "If you did not request this, you can safely ignore this email."
    )
    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user,
            password=settings.smtp_password,
            start_tls=settings.smtp_use_tls,
        )
    except Exception:
        # Don't leak SMTP errors to the caller (avoids revealing whether an
        # email address exists in the system, and avoids crashing the
        # request path over a transient relay hiccup); the caller always
        # returns a generic "check your email" response regardless.
        logger.exception("Failed to send magic-link email to %s", to_address)
