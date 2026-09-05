"""Renders a human-readable alert message from a change_event + watch pair."""


def render_message(watch: dict, change_event: dict) -> tuple[str, str]:
    """Return (subject, body) for a change alert."""
    subject_kind = "callsign" if watch["subject_type"] == "callsign" else (
        "ULS ID" if watch["subject_type"] == "uls_id" else "ASR registration number"
    )
    subject_value = watch["subject_value"]

    subject_line = f"FCC ULS Explorer: change detected for {subject_value}"

    old_value = change_event["old_value"] if change_event["old_value"] not in (None, "") else "(blank)"
    new_value = change_event["new_value"] if change_event["new_value"] not in (None, "") else "(blank)"

    body = (
        f"A change was detected for the {subject_kind} you are watching: {subject_value}\n\n"
        f"Field: {change_event['field_name']}\n"
        f"Old value: {old_value}\n"
        f"New value: {new_value}\n"
        f"Effective date: {change_event['effective_date']}\n"
        f"Source file: {change_event['source_file']}\n"
        f"Detected at: {change_event['detected_at']}\n"
    )
    return subject_line, body
