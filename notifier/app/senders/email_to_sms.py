"""Email-to-SMS gateway sender: reuses the SMTP sender, since sending a text
via a carrier's free email-to-SMS gateway (e.g. 5551234567@vtext.com) is
just an email under the hood -- an FOSS-friendly way to reach a phone
without a paid SMS API."""
from .base import SendError
from .smtp import send_smtp

# A handful of well-known US carrier gateways. Not exhaustive -- callers can
# always supply "address" directly in config to bypass this table entirely.
CARRIER_GATEWAYS = {
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "boost": "sms.myboostmobile.com",
    "cricket": "sms.cricketwireless.net",
    "uscellular": "email.uscc.net",
}


def send_email_to_sms(config: dict, subject: str, body: str) -> None:
    address = config.get("address")
    if not address:
        phone = config.get("phone")
        carrier = config.get("carrier")
        gateway = config.get("carrier_gateway") or CARRIER_GATEWAYS.get((carrier or "").lower())
        if not phone or not gateway:
            raise SendError(
                "email_to_sms channel config needs either 'address', or "
                "'phone' plus 'carrier' (one of: " + ", ".join(CARRIER_GATEWAYS) + ") "
                "or an explicit 'carrier_gateway'"
            )
        address = f"{phone}@{gateway}"

    # SMS gateways truncate aggressively; keep the body short and drop the subject line.
    short_body = body.strip().splitlines()[0] if body.strip() else subject
    send_smtp({"email": address}, subject="", body=short_body[:140])
