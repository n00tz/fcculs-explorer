"""Unit tests for message rendering and sender payload shaping (no network,
no DB -- pure logic, using unittest.mock to intercept the actual HTTP/SMTP
calls at the sender boundary)."""
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, "/app")

from app.render import render_message, render_test_message, PLATFORM_MESSAGE_LIMITS
from app.senders.email_to_sms import send_email_to_sms
from app.senders.presets import send_discord, send_matrix, send_ntfy, send_telegram
from app.senders.webhook import _substitute, send_webhook
from app.senders.base import SendError


class TestRenderMessage(unittest.TestCase):
    def test_renders_expected_fields(self):
        watch = {"subject_type": "callsign", "subject_value": "KM4TYD"}
        change_event = {
            "field_name": "license_status",
            "old_value": "A",
            "new_value": "E",
            "source_file": "l_am_mon.zip",
            "effective_date": "2026-09-02",
            "detected_at": "2026-09-02T00:00:00Z",
        }
        subject, body = render_message(watch, change_event)
        self.assertIn("KM4TYD", subject)
        self.assertIn("license_status", body)
        self.assertIn("Old value: A", body)
        self.assertIn("New value: E", body)

    def test_blank_values_rendered_as_blank_placeholder(self):
        watch = {"subject_type": "uls_id", "subject_value": "232195"}
        change_event = {
            "field_name": "call_sign",
            "old_value": "",
            "new_value": "KM4TYD",
            "source_file": "l_am_mon.zip",
            "effective_date": "2026-09-02",
            "detected_at": "2026-09-02T00:00:00Z",
        }
        _, body = render_message(watch, change_event)
        self.assertIn("Old value: (blank)", body)


class TestRenderTestMessage(unittest.TestCase):
    """render_test_message() powers the 'Send test' feature: a verbose,
    self-explanatory message not tied to any real watch/change_event,
    truncated to each platform's practical message-length limit so the
    test message itself demonstrates the real constraint."""

    def test_returns_subject_and_body_for_every_known_channel_type(self):
        for channel_type in PLATFORM_MESSAGE_LIMITS:
            subject, body = render_test_message(channel_type)
            self.assertTrue(subject)
            self.assertTrue(body)
            self.assertIn("TEST", body)

    def test_body_respects_platform_length_limit(self):
        for channel_type, limit in PLATFORM_MESSAGE_LIMITS.items():
            _, body = render_test_message(channel_type)
            # A little slack is allowed for a short trailing truncation
            # marker, but the body must never balloon past the platform's
            # practical ceiling.
            self.assertLessEqual(len(body), limit + 50, f"{channel_type} body too long: {len(body)} chars")

    def test_email_to_sms_body_is_short(self):
        # email_to_sms's own sender hard-truncates to 140 chars regardless,
        # but the rendered test body should already respect that limit.
        _, body = render_test_message("email_to_sms")
        self.assertLessEqual(len(body), 190)

    def test_unknown_channel_type_falls_back_to_default_limit(self):
        subject, body = render_test_message("some_future_channel_type")
        self.assertTrue(subject)
        self.assertLessEqual(len(body), 4050)


class TestWebhookSubstitution(unittest.TestCase):
    def test_substitutes_nested_placeholders(self):
        payload = {"content": "{subject}: {body}", "meta": {"nested": "{body}"}}
        result = _substitute(payload, "SUBJ", "BODY")
        self.assertEqual(result["content"], "SUBJ: BODY")
        self.assertEqual(result["meta"]["nested"], "BODY")


class TestWebhookSsrfGuard(unittest.TestCase):
    """send_webhook/send_ntfy must reject unsafe URLs before ever calling
    httpx, and never follow redirects for URLs that do pass."""

    def test_send_webhook_rejects_internal_url_without_calling_httpx(self):
        with patch("app.senders.webhook.httpx.request") as mock_request:
            with patch("app.url_safety.socket.getaddrinfo", return_value=[(None, None, None, None, ("10.0.0.5", 0))]):
                with self.assertRaises(SendError):
                    send_webhook({"url": "http://postgres:5432/"}, "s", "b")
            mock_request.assert_not_called()

    def test_send_webhook_calls_httpx_without_follow_redirects_kwarg(self):
        # httpx.request's own default for follow_redirects is False; this
        # test just confirms we don't override it to True anywhere.
        with patch("app.senders.webhook.httpx.request") as mock_request:
            with patch("app.url_safety.socket.getaddrinfo", return_value=[(None, None, None, None, ("93.184.216.34", 0))]):
                send_webhook({"url": "https://example.com/hook"}, "s", "b")
            _, kwargs = mock_request.call_args
            self.assertNotIn("follow_redirects", kwargs)

    def test_send_ntfy_rejects_internal_url_without_calling_httpx(self):
        with patch("app.senders.presets.httpx.post") as mock_post:
            with patch("app.url_safety.socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
                with self.assertRaises(SendError):
                    send_ntfy({"url": "http://localhost/topic"}, "s", "b")
            mock_post.assert_not_called()


class TestEmailToSmsSender(unittest.TestCase):
    def test_builds_address_from_carrier(self):
        with patch("app.senders.email_to_sms.send_smtp") as mock_send:
            send_email_to_sms(
                {"phone": "5551234567", "carrier": "verizon"}, "Subject", "Body line\nmore"
            )
            args, kwargs = mock_send.call_args
            self.assertEqual(args[0]["email"], "5551234567@vtext.com")
            self.assertEqual(kwargs["body"], "Body line"[:140])

    def test_uses_explicit_address(self):
        with patch("app.senders.email_to_sms.send_smtp") as mock_send:
            send_email_to_sms({"address": "custom@sms.example"}, "Subject", "Body")
            args, kwargs = mock_send.call_args
            self.assertEqual(args[0]["email"], "custom@sms.example")

    def test_raises_when_no_gateway_resolvable(self):
        with self.assertRaises(SendError):
            send_email_to_sms({"phone": "5551234567", "carrier": "not-a-real-carrier"}, "s", "b")


class TestPresetSenders(unittest.TestCase):
    def test_discord_shapes_content_payload(self):
        with patch("app.senders.presets.send_webhook") as mock_send:
            send_discord({"url": "https://discord.example/webhook"}, "Subj", "Body")
            config_arg = mock_send.call_args[0][0]
            self.assertIn("Subj", config_arg["payload_template"]["content"])
            self.assertIn("Body", config_arg["payload_template"]["content"])

    def test_telegram_requires_bot_token_and_chat_id(self):
        with self.assertRaises(SendError):
            send_telegram({}, "s", "b")

    def test_matrix_requires_full_config(self):
        with self.assertRaises(SendError):
            send_matrix({"homeserver": "https://matrix.example"}, "s", "b")


if __name__ == "__main__":
    unittest.main()
