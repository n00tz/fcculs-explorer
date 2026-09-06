"""Email-to-SMS gateway sender: reuses the SMTP sender, since sending a text
via a carrier's free email-to-SMS gateway (e.g. 5551234567@vtext.com) is
just an email under the hood -- an FOSS-friendly way to reach a phone
without a paid SMS API."""
from .base import SendError
from .smtp import send_smtp

# Major US carriers + large MVNOs' email-to-SMS gateway domains. These are
# community-documented, unofficial conventions -- not a published/supported
# API -- so carriers can change or discontinue them without notice; treat
# this table as best-effort. Callers can always supply "address" directly
# in config (or an explicit "carrier_gateway") to bypass this table entirely
# if a gateway below stops working or a carrier isn't listed.
CARRIER_GATEWAYS = {
    # Big 3 national carriers
    "verizon": "vtext.com",
    "att": "txt.att.net",
    "tmobile": "tmomail.net",
    # Sprint's network was decommissioned into T-Mobile in 2022; gateway
    # kept for legacy accounts that may still route through it.
    "sprint": "messaging.sprintpcs.com",
    # Large MVNOs / prepaid brands
    "boost": "sms.myboostmobile.com",
    "cricket": "sms.cricketwireless.net",
    "uscellular": "email.uscc.net",
    "metro": "mymetropcs.com",
    "googlefi": "msg.fi.google.com",
    "straighttalk": "vtext.com",
    "consumercellular": "mailmymobile.net",
    "xfinitymobile": "vtext.com",
    "republicwireless": "text.republicwireless.com",
    "ting": "message.ting.com",
    "virginmobile": "vmobl.com",
    "pageplus": "vtext.com",
    "simplemobile": "smtext.com",
    "tracfone": "mmst5.tracfone.com",
    "mintmobile": "tmomail.net",
    "visible": "vtext.com",
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
