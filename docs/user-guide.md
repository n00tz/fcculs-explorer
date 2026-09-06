# FCC ULS Explorer — User Guide

This guide covers how to **use** the FCC ULS Explorer web application:
searching, browsing, filtering, reading detail pages, signing in, and
managing watches/alerts. It does not cover installing, deploying, or
administering the service — see `README.md` for that.

> **Note on alerts**: watches and notification channels can be created
> today, but actual email/text/webhook delivery depends on an SMTP relay
> being configured by the operator running this instance. If that hasn't
> been set up yet, watches will still be recorded, but you won't receive
> notifications until it is. Ask your instance's operator if you're
> unsure.

## Contents

- [What's in here](#whats-in-here)
- [Searching](#searching)
- [Browsing and filtering Amateur Radio licenses](#browsing-and-filtering-amateur-radio-licenses)
- [Browsing and filtering Tower registrations](#browsing-and-filtering-tower-registrations)
- [Reading a detail page](#reading-a-detail-page)
- [Signing in](#signing-in)
- [My Watches: alerts on changes](#my-watches-alerts-on-changes)
- [Notification channel types](#notification-channel-types)
- [Frequently asked questions](#frequently-asked-questions)

## What's in here

Two FCC datasets, refreshed daily from the FCC's public ULS transaction
files:

- **Amateur Radio Service** — every licensed callsign: licensee name and
  address, operator class, license status, grant/expiration dates, and
  (for club/military recreation stations) the trustee callsign.
- **Antenna Structure Registrations ("Towers")** — every FCC-registered
  antenna structure: owner/entity, location, height, structure type, FAA
  study number, and construction/dismantle dates.

Both datasets carry their full **change history**, so you can see not just
the current state of a callsign or tower, but everything that's changed
about it over time.

## Searching

The home page (`/`) is a single search box. Type at least 2 characters —
results appear automatically after a short pause, or click **Search**.

You can search by:
- **Callsign** — full or partial, e.g. `W1AW` or `W1A`
- **ASR registration number** — the tower's FCC registration number
- **Licensee or entity name** — e.g. `Sloan`

Results are ranked with exact matches first, then close/partial matches
(callsigns like `W1AWP`, `W1AWR` will show up under a `W1AW` search).  Each
result shows what kind of record it is (Callsign, Amateur Licensee, Tower
Registration, Tower Entity) — click through to its detail page.

If you already know exactly what you're browsing for (all Amateur records
in a state, all towers over a certain height, etc.) the **Amateur** and
**Towers** browse pages (linked from the top nav) support much richer
filtering than the home page search box — see below.

## Browsing and filtering Amateur Radio licenses

Go to **Amateur** in the navigation. Every field shown in the results table
can be filtered, and all text filters are **partial matches** — you don't
need to type the whole value:

| Filter | Matches | Example |
|---|---|---|
| Callsign | anywhere in the callsign | `N0O` matches `N0OTZ` |
| Licensee name | anywhere in the licensee's entity name, first name, or last name | `Sloan` matches "Sloan, Rial F" |
| City | anywhere in the city name | `ring` matches "Ringgold" |
| State | anywhere in the 2-letter state code | `GA` |
| Status | exact match, pick from the dropdown | Active / Expired / Cancelled / Terminated |
| Operator class | exact match (Technician, General, Amateur Extra, etc.) | `G` |

Combine as many filters as you like, then click **Apply filters**. Results
are paginated 25 at a time; use **Previous**/**Next** to page through.

Click any callsign in the results to open its full detail page.

## Browsing and filtering Tower registrations

Go to **Towers** in the navigation. Same idea as Amateur — every displayed
column is filterable, and text fields are partial matches:

| Filter | Matches | Example |
|---|---|---|
| Registration # | anywhere in the registration number | `100` |
| Structure type | anywhere in the type (TOWER, MTOWER, POLE, GTOWER, ...) | `tower` |
| City | anywhere in the city name | `atlanta` |
| State | anywhere in the 2-letter state code | `GA` |
| Status | exact match, pick from the dropdown | Constructed / Granted / Dismantled |
| Min / Max height (AGL, ft) | numeric range on height above ground | `500` and up |
| Constructed after / before | date range on construction date | `2020-01-01` onward |

Click any registration number in the results to open its full detail page.

## Reading a detail page

### Amateur callsign detail

- **Header**: the callsign, current license status, licensee name,
  location, FRN, operator class, group code, trustee callsign (if a
  club/military station), grant date, expiration date, and the internal
  ULS System ID.
- **Related Identities (same FRN)**: other callsigns or tower
  registrations tied to the same FCC Registration Number (FRN) — this is
  how you discover, for example, a person's prior or additional
  callsigns.
- **Change History**: every detected field-level change (old value → new
  value) pulled from FCC's daily transaction files, with the date FCC
  says the change was effective and the date it was detected here.
- **License History**: the raw FCC history log for the callsign, each row
  annotated with a **Meaning** column explaining what that log code
  represents (e.g. a vanity callsign grant, a renewal, a modification).

**Important — a callsign can have more than one holder over time.** FCC
reissues expired callsigns as vanity calls to new licensees. The detail
page always shows the **current holder's** information at the top,
resolved as: prefer the active license, otherwise the most recently
granted one. The **License History** table below it still shows the
*entire* timeline across every holder — so you can see a prior holder's
expiration alongside your own grant date on the same page.

### Tower detail

- **Header**: registration number, status, structure type, location,
  height above ground and above mean sea level, construction date, FAA
  study number.
- **Owners / Contacts**: the entity/entities associated with the
  registration.
- **Coordinates**: registered antenna coordinate(s).
- **Other Towers at This Site**: other registered structures sharing the
  same site coordinates — useful for finding co-located towers.
- **Related Identities (same FRN)**: other Amateur callsigns or tower
  registrations tied to the same FRN as this tower's owner.
- **Change History**: same field-level change log as Amateur detail pages.

## Signing in

Watches and notification channels require an account, but there's no
separate sign-up step or password to remember:

1. Go to **My Watches** (or click **Sign in**).
2. Enter your email address and click **Send sign-in link**.
3. Check your inbox for an email with a one-time link, valid for
   **15 minutes**.
4. Click the link — you're signed in, and an account is created
   automatically the first time.

For privacy, the app always responds the same way ("if that email is
valid, a link has been sent") whether or not an account already exists for
that address, so no one can use the sign-in form to discover who has an
account.

Sessions are cookie-based; use **Sign out** (on the My Watches page) to end
your session on a shared computer.

> Since the sign-in link is emailed, an operator must have SMTP configured
> for you to actually receive it. If you request a link and nothing
> arrives, check with your instance's operator.

## My Watches: alerts on changes

Once signed in, **My Watches** lets you:

1. **Add a notification channel** — where alerts should be delivered (see
   [channel types](#notification-channel-types) below for the config
   format each one expects).
2. **Add a watch** — pick what to watch and which channel to notify:
   - **Callsign** — e.g. `K0WNL`
   - **ULS System ID** — the internal numeric ID shown on a detail page
   - **ASR Registration Number** — a tower's registration number
3. When the daily FCC data refresh detects a change to something you're
   watching, a notification is sent through your chosen channel(s).

You can have multiple watches pointing at different channels (e.g. get a
push notification for one callsign and an email for another), and multiple
channels of the same type (e.g. two different webhook URLs). Delete a
watch or channel at any time from the same page; deleting a channel that
still has watches attached will stop those watches from being able to
deliver until you point them at a different channel.

**What counts as a "change"?** Anything the daily ingestion detects as
different from what was previously stored for that identity — for
example, a status change, an address update, a renewal/expiration date
change, or a reassignment. The same field-level list appears in the
**Change History** section of the identity's own detail page, so you can
always see what triggered (or would trigger) an alert.

## Notification channel types

| Type | What it needs | Notes |
|---|---|---|
| Email (SMTP) | `{"email": "you@example.com"}` | Delivered via the instance's configured SMTP relay. |
| Email-to-SMS | `{"phone": "5551234567", "carrier": "verizon"}` | Sends a text via your carrier's free email-to-SMS gateway — no paid SMS API involved. Supported `carrier` values: `verizon`, `att`, `tmobile`, `sprint`, `boost`, `cricket`, `uscellular`. If your carrier isn't listed, supply `"carrier_gateway": "yourcarrier.example"` directly instead of `carrier`. |
| Generic Webhook | `{"url": "https://example.com/hook"}` | POSTs a JSON payload to any URL you control. |
| ntfy | `{"url": "https://ntfy.sh/your-topic"}` | Push notifications via the free [ntfy.sh](https://ntfy.sh) service (or a self-hosted ntfy server). |
| Discord | `{"url": "https://discord.com/api/webhooks/..."}` | A Discord channel webhook URL. |
| Telegram | `{"bot_token": "123:abc", "chat_id": "123456"}` | Requires a Telegram bot token and the target chat ID. |
| Matrix | `{"homeserver": "https://matrix.org", "room_id": "!abc:matrix.org", "access_token": "..."}` | Posts into a Matrix room. |

The **Add a channel** form pre-fills the config box with the right
template for whichever type you pick from the dropdown — just edit the
values and submit.

## Frequently asked questions

**Why does a callsign's detail page show someone else's expired license
info in the history table?**
That's expected and intentional — FCC reissues expired callsigns as vanity
calls. The top of the page always shows the *current* holder; the License
History table below shows every holder's activity on that callsign over
time, so you can see the full lineage.

**How often is the data updated?**
Daily, from FCC's public transaction files. The exact time depends on your
instance's configuration (an operator setting, not something you control
from the UI).

**I searched for something and got no results — is the data missing?**
This instance only covers Amateur Radio Service and Antenna Structure
Registration (Tower) data — no other FCC ULS services (commercial,
GMRS, etc.) are included in v1. Double-check spelling/partial terms, or
try the dedicated Amateur/Towers browse pages with filters instead of the
home page search box.

**I created a watch but haven't gotten an alert — is something wrong?**
Nothing changed yet for what you're watching, or (see the note at the top
of this guide) your instance's SMTP relay may not be configured yet, which
would prevent email and email-to-SMS delivery specifically (webhook-based
channels like ntfy/Discord/Telegram/Matrix/generic webhook don't depend on
SMTP). Check with your operator.
