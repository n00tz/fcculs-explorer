"""Generic HTTP webhook sender -- posts a JSON payload to a user-supplied
URL. Used both directly (channel_type='webhook') and as the basis for the
ntfy/Discord/Telegram/Matrix presets below."""
import httpx

from .base import SendError
from ..url_safety import UnsafeUrlError, assert_safe_webhook_url


def send_webhook(config: dict, subject: str, body: str) -> None:
    url = config.get("url")
    if not url:
        raise SendError("webhook channel config missing 'url'")

    try:
        assert_safe_webhook_url(url)
    except UnsafeUrlError as exc:
        raise SendError(f"webhook URL rejected: {exc}") from exc

    method = (config.get("method") or "POST").upper()
    payload = config.get("payload_template") or {"subject": subject, "body": body}
    if isinstance(payload, dict):
        payload = _substitute(payload, subject, body)

    headers = config.get("headers") or {}

    try:
        # follow_redirects intentionally left at the httpx default (False):
        # a redirect could point at an internal address we'd otherwise
        # block, so we never follow one for a user-supplied webhook URL.
        resp = httpx.request(method, url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise SendError(f"webhook delivery failed: {exc}") from exc


def _substitute(payload: dict, subject: str, body: str) -> dict:
    """Replace the literal strings '{subject}'/'{body}' anywhere in a
    user-supplied payload template so callers can shape the JSON body to
    match a specific webhook API (e.g. {"text": "{body}"})."""
    def replace(value):
        if isinstance(value, str):
            return value.replace("{subject}", subject).replace("{body}", body)
        if isinstance(value, dict):
            return {k: replace(v) for k, v in value.items()}
        if isinstance(value, list):
            return [replace(v) for v in value]
        return value

    return replace(payload)
