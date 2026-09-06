"""ntfy / Discord / Telegram / Matrix presets -- each is a thin adapter that
shapes the message into that service's expected payload and delegates the
actual HTTP call to the generic webhook sender, so all FOSS-friendly text
channels share one retry/error-handling code path."""
import httpx

from .base import SendError
from .webhook import send_webhook
from ..url_safety import UnsafeUrlError, assert_safe_webhook_url


def send_ntfy(config: dict, subject: str, body: str) -> None:
    """ntfy.sh (or self-hosted ntfy): POST plain text to the topic URL,
    title carried via a header."""
    url = config.get("url")
    if not url:
        raise SendError("ntfy channel config missing 'url' (e.g. https://ntfy.sh/your-topic)")
    try:
        assert_safe_webhook_url(url)
    except UnsafeUrlError as exc:
        raise SendError(f"ntfy URL rejected: {exc}") from exc
    try:
        resp = httpx.post(
            url,
            content=body.encode("utf-8"),
            headers={"Title": subject, **(config.get("headers") or {})},
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SendError(f"ntfy delivery failed: {exc}") from exc


def send_discord(config: dict, subject: str, body: str) -> None:
    """Discord incoming webhook: {"content": "..."} JSON payload."""
    webhook_config = {**config, "payload_template": {"content": f"**{subject}**\n{body}"}}
    send_webhook(webhook_config, subject, body)


def send_telegram(config: dict, subject: str, body: str) -> None:
    """Telegram Bot API sendMessage. config needs 'bot_token' and 'chat_id'."""
    bot_token = config.get("bot_token")
    chat_id = config.get("chat_id")
    if not bot_token or not chat_id:
        raise SendError("telegram channel config needs 'bot_token' and 'chat_id'")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    webhook_config = {"url": url, "payload_template": {"chat_id": chat_id, "text": f"{subject}\n\n{body}"}}
    send_webhook(webhook_config, subject, body)


def send_matrix(config: dict, subject: str, body: str) -> None:
    """Matrix room message via the Client-Server API. config needs
    'homeserver', 'room_id', 'access_token'."""
    homeserver = config.get("homeserver")
    room_id = config.get("room_id")
    access_token = config.get("access_token")
    if not homeserver or not room_id or not access_token:
        raise SendError("matrix channel config needs 'homeserver', 'room_id', 'access_token'")
    url = f"{homeserver.rstrip('/')}/_matrix/client/v3/rooms/{room_id}/send/m.room.message"
    webhook_config = {
        "url": url,
        "method": "POST",
        "headers": {"Authorization": f"Bearer {access_token}"},
        "payload_template": {"msgtype": "m.text", "body": f"{subject}\n\n{body}"},
    }
    send_webhook(webhook_config, subject, body)
