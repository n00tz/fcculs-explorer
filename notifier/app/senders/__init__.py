"""Registry mapping notification_channels.channel_type -> sender function."""
from .email_to_sms import send_email_to_sms
from .presets import send_discord, send_matrix, send_ntfy, send_telegram
from .smtp import send_smtp
from .webhook import send_webhook

SENDERS = {
    "smtp": send_smtp,
    "email_to_sms": send_email_to_sms,
    "webhook": send_webhook,
    "ntfy": send_ntfy,
    "discord": send_discord,
    "telegram": send_telegram,
    "matrix": send_matrix,
}
