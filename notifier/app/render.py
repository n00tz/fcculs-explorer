"""Renders a human-readable alert message from a change_event + watch pair."""

_SUBJECT_KIND_LABELS = {
    "callsign": "callsign",
    "uls_id": "ULS ID",
    "asr_registration_number": "ASR registration number",
    "frn": "FRN",
}

# field_name values the ingestor uses for its synthetic "brand new record"
# events (see ingestor/ingest.py's NEW_RECORD_FRN_EVENT) -- rendered with
# different wording than an ordinary field-change event, since there's no
# "old value" to speak of.
_NEW_RECORD_FIELD_NAMES = {"license_granted", "tower_registered"}

_NEW_RECORD_DESCRIPTIONS = {
    "license_granted": "a new amateur radio callsign has been granted",
    "tower_registered": "a new tower registration has been recorded",
}


def render_message(watch: dict, change_event: dict) -> tuple[str, str]:
    """Return (subject, body) for a change alert."""
    subject_kind = _SUBJECT_KIND_LABELS.get(watch["subject_type"], watch["subject_type"])
    subject_value = watch["subject_value"]
    field_name = change_event["field_name"]

    if field_name in _NEW_RECORD_FIELD_NAMES:
        subject_line = f"FCC ULS Explorer: {_NEW_RECORD_DESCRIPTIONS[field_name]} for FRN {subject_value}" if watch["subject_type"] == "frn" else f"FCC ULS Explorer: new record for {subject_value}"
        body = (
            f"Good news: {_NEW_RECORD_DESCRIPTIONS[field_name]} for the {subject_kind} you are "
            f"watching: {subject_value}\n\n"
            f"New identifier: {change_event['new_value']}\n"
            f"Effective date: {change_event['effective_date']}\n"
            f"Source file: {change_event['source_file']}\n"
            f"Detected at: {change_event['detected_at']}\n\n"
            f"You can now also watch \"{change_event['new_value']}\" directly (as a callsign or ASR "
            f"registration number) to be alerted on any future changes to it specifically.\n"
        )
        return subject_line, body

    subject_line = f"FCC ULS Explorer: change detected for {subject_value}"

    old_value = change_event["old_value"] if change_event["old_value"] not in (None, "") else "(blank)"
    new_value = change_event["new_value"] if change_event["new_value"] not in (None, "") else "(blank)"

    body = (
        f"A change was detected for the {subject_kind} you are watching: {subject_value}\n\n"
        f"Field: {field_name}\n"
        f"Old value: {old_value}\n"
        f"New value: {new_value}\n"
        f"Effective date: {change_event['effective_date']}\n"
        f"Source file: {change_event['source_file']}\n"
        f"Detected at: {change_event['detected_at']}\n"
    )
    return subject_line, body


# Practical per-platform message-length limits used to truncate the verbose
# test message below, so a test-send actually demonstrates what a real alert
# will look like on that platform rather than just describing the limit in
# prose. email_to_sms's sender already hard-truncates to 140 chars itself
# (see email_to_sms.py) regardless of what's passed in here; the other
# limits are the platform's own practical ceiling (Discord's 2000-char
# message body limit, Telegram's 4096-char sendMessage limit, etc.) --
# smtp/webhook/ntfy/matrix have no hard platform limit worth enforcing here,
# so they get a generous but still-bounded cap.
PLATFORM_MESSAGE_LIMITS = {
    "smtp": 4000,
    "email_to_sms": 140,
    "webhook": 4000,
    "ntfy": 4000,
    "discord": 2000,
    "telegram": 4096,
    "matrix": 4000,
}


def render_test_message(channel_type: str) -> tuple[str, str]:
    """Return (subject, body) for a test-send -- a verbose, self-explanatory
    message (not tied to any real watch/change_event) that shows the user
    what a real alert will look like, truncated to this channel type's
    practical message-length limit so the test message itself demonstrates
    the real constraint rather than just describing it."""
    limit = PLATFORM_MESSAGE_LIMITS.get(channel_type, 4000)
    subject = "FCC ULS Explorer: test notification"

    full_body = (
        "This is a TEST message from FCC ULS Explorer to confirm this notification "
        "channel is working. No real license or tower change has occurred.\n\n"
        "When a real change happens on something you're watching, you'll receive a "
        "message like this:\n\n"
        "FCC ULS Explorer: change detected for N0OTZ\n"
        "Field: license_status\n"
        "Old value: A\n"
        "New value: E\n"
        "Effective date: 2026-09-01\n"
        "Source file: l_am_mon.zip\n"
        "Detected at: 2026-09-02 07:03:11 UTC\n\n"
        "If you watched an FRN instead of a callsign (e.g. a brand-new ham waiting "
        "for their first callsign to be granted), the message instead announces the "
        "new callsign/tower as soon as it appears.\n\n"
        f"This channel type ({channel_type}) has a practical message-length limit of "
        f"about {limit} characters"
        + (" (SMS gateways truncate aggressively, so real alerts are kept very short)" if channel_type == "email_to_sms" else "")
        + " -- this test message is truncated to demonstrate that limit if needed."
    )

    if len(full_body) > limit:
        # Leave room for a truncation marker so it's obvious the cut is
        # intentional, not a bug -- mirrors what a user will actually see
        # on a real over-limit alert on this platform.
        marker = "… [truncated]"
        full_body = full_body[: max(limit - len(marker), 0)] + marker

    return subject, full_body
