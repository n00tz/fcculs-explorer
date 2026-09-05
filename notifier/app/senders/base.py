"""Sender interface: every notification_channels.channel_type maps to a
function(config: dict, subject: str, body: str) -> None that raises on
failure (caught by the caller, which records last_error/attempts)."""
from typing import Callable, Protocol


class SendError(Exception):
    """Raised by a sender when delivery fails; message becomes last_error."""


class Sender(Protocol):
    def __call__(self, config: dict, subject: str, body: str) -> None: ...
