"""SMTP sender: delivers a plain-text email via a BYO SMTP relay (no
third-party API key dependency, per the project's FOSS-only requirement)."""
import smtplib
from email.message import EmailMessage

from ..config import settings
from .base import SendError


def send_smtp(config: dict, subject: str, body: str) -> None:
    to_address = config.get("email")
    if not to_address:
        raise SendError("smtp channel config missing 'email'")

    message = EmailMessage()
    message["From"] = settings.smtp_from_address
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
            if settings.smtp_use_tls:
                client.starttls()
            if settings.smtp_user:
                client.login(settings.smtp_user, settings.smtp_password or "")
            client.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        raise SendError(f"SMTP delivery failed: {exc}") from exc
