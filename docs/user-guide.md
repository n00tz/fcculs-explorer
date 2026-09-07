# FCC ULS Explorer — User Guide

This guide covers how to **use** the FCC ULS Explorer web application:
searching, browsing, filtering, reading detail pages, signing in, setting
up alerts, and finding the "New Hams" celebration. It's written so that
even a young or brand-new ham can follow along — no technical background
needed. This guide does not cover installing, deploying, or administering
the service — see `README.md` for that.

> **Note on alerts**: watches and notification channels can be created
> today, but actual email/text/webhook delivery depends on an SMTP relay
> being configured by the operator running this instance. If that hasn't
> been set up yet, watches will still be recorded, but you won't receive
> notifications until it is. Ask your instance's operator if you're
> unsure. You can always use the **Send test** button (see below) to
> check whether a channel is actually working.

## Contents

- [What's in here](#whats-in-here)
- [The home page](#the-home-page)
- [🎉 New Hams: celebrating brand-new licenses](#-new-hams-celebrating-brand-new-licenses)
- [Searching](#searching)
- [Browsing and filtering Amateur Radio licenses](#browsing-and-filtering-amateur-radio-licenses)
- [Browsing and filtering Tower registrations](#browsing-and-filtering-tower-registrations)
- [Browsing GMRS, Aircraft, and Ship licenses](#browsing-gmrs-aircraft-and-ship-licenses)
- [Sorting any table by column](#sorting-any-table-by-column)
- [What do all these codes and abbreviations mean?](#what-do-all-these-codes-and-abbreviations-mean)
- [Reading a detail page](#reading-a-detail-page)
- [Signing in — no password needed](#signing-in--no-password-needed)
- [My Watches: alerts on changes](#my-watches-alerts-on-changes)
  - [I'm a brand-new ham and don't have a callsign yet — how do I get notified?](#im-a-brand-new-ham-and-dont-have-a-callsign-yet--how-do-i-get-notified)
  - [Setting up a notification channel (no JSON typing required)](#setting-up-a-notification-channel-no-json-typing-required)
  - [Notification channel types, explained](#notification-channel-types-explained)
  - [Testing a channel before you rely on it](#testing-a-channel-before-you-rely-on-it)
  - ["Watch this" shortcuts on detail pages](#watch-this-shortcuts-on-detail-pages)
- [Frequently asked questions](#frequently-asked-questions)

## What's in here

Five FCC datasets, refreshed every day from the FCC's public ULS
transaction files:

- **Amateur Radio Service** — every licensed ham radio callsign: the
  licensee's name and address, operator class (like Technician, General,
  or Amateur Extra), license status, grant/expiration dates, and (for
  club/military recreation stations) the trustee's callsign.
- **GMRS (General Mobile Radio Service)** — licences for the walkie-talkie
  style radios a lot of families, off-roaders and neighbourhood groups
  use. A GMRS licence covers the person who holds it *and* their whole
  immediate family, and unlike ham radio there's no exam. Lots of hams
  hold a GMRS licence too — and because we group by FRN, you'll see both
  on the same page.
- **Aircraft radio stations (Part 87)** — radio licences for aircraft.
  Most flying inside the US doesn't need one, but international flights
  and some commercial operations do. These records include the aircraft's
  **N-number** (the tail number painted on the outside), so you can look
  a plane up by the number you can actually see.
- **Ship radio stations (Part 80)** — radio licences for boats and ships.
  Small recreational boats in US waters usually don't need one, but ships
  going on international voyages do. These records include the ship's
  name, its **MMSI** (a nine-digit number that identifies a vessel on the
  radio, a bit like a phone number for a boat), how big it is, and what
  radio and emergency equipment it carries.
- **Antenna Structure Registrations ("Towers")** — every FCC-registered
  radio/antenna tower: who owns it, where it is, how tall it is, what
  kind of structure it is, its FAA study number, and when it was built or
  taken down.

Every dataset carries its full **change history**, so you can see not
just the current state of a callsign or tower, but everything that's
changed about it over time — like a diary of everything the FCC has
recorded.

## The home page

The home page (`/`) is designed to give you a quick feel for everything
the site can do, even before you search for anything:

- A short **welcome section** at the top explains, in plain language,
  that you can search/browse the data for free, and that you can sign in
  with just your email (no password!) to get notified by email, text
  message, or another app whenever something changes.
- Right below that is the **search box** — the fastest way to jump
  straight to a callsign, tower, or name (see [Searching](#searching)).
- Below the search box is the **🎉 New Hams** section — see the next
  part of this guide.
- Below that is a row of three cards explaining, in a nutshell, what you
  can do here: **Browse & search**, **Discover related identities**, and
  **Get notified — no password required**.

## 🎉 New Hams: celebrating brand-new licenses

Right on the home page, just under the search box, there's a small
celebration list called **🎉 New Hams**. This shows real people (and
clubs) who were **just granted their very first amateur radio license**
— in other words, brand-new hams who have never held a callsign before,
from **the last 10 days**.

At the top of the list you'll see two numbers, like:

> **3** new amateur radio operators licensed · **1** new club stations

- The first number is individual people who just earned their first
  callsign.
- The second number is brand-new **club stations** (like a school radio
  club or an amateur radio club) getting their first callsign.

Below the summary is a small table showing, for each new grant:

- **Callsign** — click it to see the full detail page.
- **Name** — the new operator's name, or the club's name.
- **Type** — a small badge that says "Individual" or "Club" so you can
  tell them apart at a glance.
- **City/State** — where they're located.
- **Grant Date** — the day the FCC granted the license.

The table is sorted newest first by **Grant Date**, and then
alphabetically by **Callsign** within each day. Because it always covers
a full 10-day stretch, you can also use it as a quick health check: if a
date in that range has no entries at all, that's usually a hint the site
missed a day of FCC data (an operator can fix that — see `README.md`).

The home page only shows 12 at a time (so the page stays a comfortable
size on a computer screen), with **Previous**/**Next** buttons if you
want to page through more. If you want the *complete* list — not just
the newest handful — scroll all the way down to the **footer** at the
bottom of any page and click **New Hams**, which opens a full,
searchable, filterable listing (you can filter by "All", "Individual
only", or "Club only").

**Why doesn't this include people who already have a callsign and just
got a second (vanity) one?** On purpose! This list is only for
first-timers — the very first time someone (or a club) shows up in the
FCC's amateur radio records at all. If someone already has a callsign and
later adds a second one, that's exciting for them, but it's not shown
here, so this stays a genuine "welcome to the hobby" celebration list
rather than getting cluttered with license changes for people who are
already hams.

**When does this update?** Automatically, every day, right after the
site pulls in the FCC's daily update. There's nothing you need to do —
just check back and the list (and the counts at the top) will reflect
whatever's new. Names drop off the list once their grant is more than
10 days old.

## Searching

The home page (`/`) is a single search box. Type at least 2 characters —
results appear automatically after a short pause, or click **Search**.

You can search by:
- **Callsign** — full or partial, e.g. `W1AW` or `W1A`. This covers every
  service at once: Amateur, GMRS, Aircraft and Ship
- **ASR registration number** — the tower's FCC registration number
- **Licensee or entity name** — e.g. `Sloan`
- **N-number** — an aircraft's tail number
- **Ship name** — e.g. `Liberty`

Results are ranked with exact matches first, then close/partial matches
(callsigns like `W1AWP`, `W1AWR` will show up under a `W1AW` search).
Each result shows what kind of record it is (Callsign, Amateur Licensee,
Tower Registration, Tower Entity, GMRS, Aircraft, Ship, N-Number, Ship
Name) — click through to its detail page.

If you already know exactly what you're browsing for (all Amateur
records in a state, all towers over a certain height, etc.) the
**Amateur**, **Towers**, **GMRS**, **Aircraft** and **Ship** browse pages
(linked from the top nav) support much richer filtering than the home
page search box — see below.

## Browsing and filtering Amateur Radio licenses

Go to **Amateur** in the navigation. Every field shown in the results
table can be filtered, and all text filters are **partial matches** —
you don't need to type the whole value:

| Filter | Matches | Example |
|---|---|---|
| Callsign | anywhere in the callsign | `N0O` matches `N0OTZ` |
| Licensee name | anywhere in the licensee's entity name, first name, or last name | `Sloan` matches "Sloan, Rial F" |
| City | anywhere in the city name | `ring` matches "Ringgold" |
| State | anywhere in the 2-letter state code | `GA` |
| Status | exact match, pick from the dropdown | Active / Expired / Cancelled / Terminated |
| Operator class | exact match (Technician, General, Amateur Extra, etc.) | `G` |

Combine as many filters as you like, then click **Apply filters**.
Results are paginated 25 at a time; use **Previous**/**Next** to page
through.

Click any callsign in the results to open its full detail page. Not sure
what one of the abbreviations (like a Status code or Operator Class)
means? See [What do all these codes and abbreviations
mean?](#what-do-all-these-codes-and-abbreviations-mean) below.

## Browsing and filtering Tower registrations

Go to **Towers** in the navigation. Same idea as Amateur — every
displayed column is filterable, and text fields are partial matches:

| Filter | Matches | Example |
|---|---|---|
| Registration # | anywhere in the registration number | `100` |
| Structure type | anywhere in the type (TOWER, MTOWER, POLE, GTOWER, ...) | `tower` |
| City | anywhere in the city name | `atlanta` |
| State | anywhere in the 2-letter state code | `GA` |
| Status | exact match, pick from the dropdown | Constructed / Granted / Dismantled |
| Min / Max height (AGL, ft) | numeric range on height above ground | `500` and up |
| Constructed after / before | date range on construction date | `2020-01-01` onward |

Click any registration number in the results to open its full detail
page.

## Browsing GMRS, Aircraft, and Ship licenses

These three services work exactly like the Amateur page — same filters,
same click-to-sort columns, same detail pages, same tooltips on every
code. Pick **GMRS**, **Aircraft**, or **Ship** from the navigation.

All three share these filters: **Callsign**, **Licensee name**, **City**,
**State** and **Status** — all partial matches except Status, which is a
dropdown. Two of them add a filter of their own:

| Service | Extra filters | Why it's useful |
|---|---|---|
| GMRS | *(none — GMRS records have no extra fields)* | |
| Aircraft | **N-number** | The tail number painted on the plane, so you can look up an aircraft you can actually see |
| Ship | **Ship name**, **MMSI** | Find a boat by its name, or by the nine-digit number it identifies itself with over the radio |

**GMRS** shows the callsign, licensee, location, and grant/expiry dates.
GMRS licences last 10 years and cover the licensee's whole immediate
family.

**Aircraft** adds the **N-number** and the **Carrier** type (Private
aircraft or Air carrier). The detail page also shows how many aircraft
the licence covers and whether it's a portable or fleet licence.

**Ship** has the most detail of any service on the site, because the FCC
collects the most about ships. On top of the usual licence information,
a ship's detail page can show:

- **Ship station** — the ship's name, MMSI, official number, gross
  tonnage, length, whether it makes international voyages, and its
  working radio frequencies.
- **Radio equipment** — a checklist of what the vessel actually carries:
  VHF, MF and HF radios, DSC (Digital Selective Calling, which lets a
  boat send a distress alert at the push of a button), INMARSAT satellite
  terminals, **EPIRB** beacons (an Emergency Position-Indicating Radio
  Beacon — it floats free and starts transmitting your position if the
  ship sinks), **SART** search-and-rescue transponders, and how many life
  rafts and lifeboats are aboard.
- **Voyage / exemption details** — where the ship is registered, who owns
  and operates it, and any exemptions it holds from carrying certain
  equipment.

Not every ship has all of these — smaller boats often just have the ship
station section. Anything the FCC didn't record simply isn't shown.

> **One thing that's Amateur-only:** the 🎉 New Hams celebration on the
> home page. That's specifically about people earning their first ham
> radio callsign by passing an exam, so GMRS, Aircraft and Ship licences
> aren't included. Everything else on the site — searching, browsing,
> sorting, detail pages, change history, identity grouping and alerts —
> works the same for all five datasets.

## Sorting any table by column

Every browse table (Amateur, Towers, GMRS, Aircraft and Ship) lets you
**click a column heading** to sort by that column — click **Callsign** to
sort
alphabetically by callsign, click **Grant** to sort by grant date, and so
on. Click the same heading again to flip between ascending (▲) and
descending (▼) order. A little arrow next to the heading shows you which
column is currently sorting the table and which direction it's going.
This works together with the filters above — you can filter down to just
the rows you care about, *and* control the order they're shown in.

## What do all these codes and abbreviations mean?

FCC data is full of short codes and abbreviations that aren't obvious at
a glance — things like a one-letter **Status** code, a numeric **Radio
Service Code**, or a two-letter **Operator Class**. To help with this,
anywhere one of these fields appears on the site:

- If the meaning fits in a short word or two, it's shown **right next to
  the code**, in parentheses, so you don't have to guess or hover over
  anything (helpful on phones/tablets, where hovering doesn't work).
- If the explanation is longer, **hover your mouse over the value** (or
  tap-and-hold on a touchscreen) to see a small tooltip pop-up explaining
  what it means.

If you'd rather see everything explained in one place, there's a full
**Field Definitions** reference page linked in the footer at the bottom
of every page. It lists every coded/abbreviated field used anywhere on
the site — Amateur, Towers, GMRS, Aircraft and Ship — along with every
known code and what it
means (and honestly says so on the rare occasion a code isn't officially
documented anywhere).

## Reading a detail page

### Amateur callsign detail

- **Header**: the callsign, current license status, licensee name,
  location, FRN, operator class, group code, trustee callsign (if a
  club/military station), grant date, expiration date, and the internal
  ULS System ID.
- **🔔 Watch this callsign / Watch this FRN**: if you're signed in,
  you'll see small "🔔 Watch this" links right next to the callsign and
  the FRN — click one to jump straight to the watch-setup page with that
  value already filled in for you. See ["Watch this" shortcuts on detail
  pages](#watch-this-shortcuts-on-detail-pages) below.
- **Related Identities (same FRN)**: other callsigns or tower
  registrations tied to the same FCC Registration Number (FRN) — this is
  how you discover, for example, a person's prior or additional
  callsigns, or that the same person also holds a GMRS, aircraft or ship
  licence. This works across all five datasets, so one FRN shows you a
  person's entire FCC footprint in one place.
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
- **Change History**: same field-level change log as Amateur detail
  pages.

## Signing in — no password needed

Watches and notification channels require an account, but there's no
separate sign-up step or password to remember — ever:

1. Go to **My Watches** (or click **Sign in**).
2. Enter your email address and click **Send sign-in link**.
3. Check your inbox for an email with a one-time link, valid for
   **15 minutes**.
4. Click the link — you're signed in, and an account is created
   automatically the first time.

That's it — no password to make up, remember, or lose. Every time you
want to sign in in the future, you just repeat these same steps and a
fresh link is emailed to you.

For privacy, the app always responds the same way ("if that email is
valid, a link has been sent") whether or not an account already exists
for that address, so no one can use the sign-in form to discover who has
an account.

Sessions are cookie-based; use **Sign out** (on the My Watches page) to
end your session on a shared computer.

> Since the sign-in link is emailed, an operator must have SMTP
> configured for you to actually receive it. If you request a link and
> nothing arrives, check with your instance's operator.

## My Watches: alerts on changes

Once signed in, **My Watches** lets you:

1. **Add a notification channel** — where alerts should be delivered
   (email, text message, or an app like Discord/Telegram). See
   [Setting up a notification channel](#setting-up-a-notification-channel-no-json-typing-required)
   below.
2. **Add a watch** — pick what to watch and which channel to notify:
   - **Callsign** — e.g. `K0WNL`
   - **FRN (FCC Registration Number)** — see the next section, this is
     the best option for a brand-new ham!
   - **ULS System ID** — the internal numeric ID shown on a detail page
   - **ASR Registration Number** — a tower's registration number
3. **Optionally narrow it to one service.** Every watch has a **Service**
   selector, and the default — **All services (recommended)** — is what
   you want almost every time. Because the FCC reuses callsign and FRN
   formats across services, one FRN watch on "All services" will tell you
   about your ham licence, your GMRS licence, and a boat or aircraft
   licence under the same FRN, all at once. Only pick a specific service
   if you deliberately want to hear about, say, GMRS changes and nothing
   else. Watches you created before this option existed keep working
   exactly as they did — they're already set to "All services".
4. When the daily FCC data refresh detects a change to something you're
   watching, a notification is sent through your chosen channel(s).

You can have multiple watches pointing at different channels (e.g. get a
push notification for one callsign and an email for another), and
multiple channels of the same type (e.g. two different webhook URLs).
Delete a watch or channel at any time from the same page; deleting a
channel that still has watches attached will stop those watches from
being able to deliver until you point them at a different channel.

**What counts as a "change"?** Anything the daily ingestion detects as
different from what was previously stored for that identity — for
example, a status change, an address update, a renewal/expiration date
change, or a reassignment. The same field-level list appears in the
**Change History** section of the identity's own detail page, so you can
always see what triggered (or would trigger) an alert.

### I'm a brand-new ham and don't have a callsign yet — how do I get notified?

This is the **most common situation**, and the site has a feature just
for it! Here's the problem it solves: when you register with the FCC
(through their CORES system), you're given an **FRN (FCC Registration
Number)** right away — but your actual **callsign** doesn't exist yet
until the FCC finishes processing your license and grants it. Up until
that moment, there's no callsign to search for or watch.

The fix: **watch your FRN instead of a callsign.** On the **My Watches**
page, right above the "Add a watch" form, you'll see a highlighted
callout box that explains this exact situation. To use it:

1. Find your FRN — it's the number you got when you registered with the
   FCC, usually a 10-digit number like `0012345678`.
2. On the **Add a watch** form, choose **"FRN (for new hams without a
   callsign yet)"** from the **Watch type** dropdown.
3. Type your FRN into the **Value** field.
4. Pick a notification channel (see below) and click **Add watch**.

The moment the FCC grants your very first callsign — or registers any
new tower — tied to that FRN, you'll get notified automatically. No more
refreshing the FCC website every day wondering if your license came
through!

### Setting up a notification channel (no JSON typing required)

Adding a channel is simple, guided, and doesn't require you to type any
code or technical formatting — just fill out a normal-looking form:

1. On **My Watches**, under **Add a channel**, pick a **Type** from the
   dropdown (Email, Email-to-SMS, Webhook, ntfy, Discord, Telegram, or
   Matrix — see the next section for what each one means).
2. The form automatically shows you the right fields for whatever type
   you picked — for example, picking "Email-to-SMS" shows a phone number
   box and a carrier dropdown; picking "Discord" shows just a single
   webhook-URL box.
3. Every field has a small **"?"** next to its label — hover over it (or
   tap it on a touchscreen) to see a plain-language explanation of what
   to put there.
4. Optionally give the channel a friendly **Label** (like "My Phone" or
   "Family Discord") so you can tell it apart from other channels later.
5. Click **Add channel**.

### Notification channel types, explained

| Type | What you'll be asked for | What it means, in plain terms |
|---|---|---|
| **Email (SMTP)** | Your email address | A regular email is sent to this address whenever something you're watching changes. |
| **Email-to-SMS** | Your phone number + your carrier (chosen from a dropdown) | Sends a text message straight to your phone — for free — using a trick your cell carrier supports called "email-to-SMS": every carrier has a hidden email address that turns into a text message on your phone. You just pick your carrier from a list; the site handles the rest. If your specific carrier or MVNO isn't in the list, there's an "Other" option where you can type in the gateway address yourself. Every major US carrier and a long list of popular prepaid/MVNO brands are supported, including Verizon, AT&T, T-Mobile, Sprint (legacy), Boost Mobile, Cricket Wireless, US Cellular, Metro by T-Mobile, Google Fi, Straight Talk, Consumer Cellular, Xfinity Mobile, Republic Wireless, Ting, Virgin Mobile, Page Plus, Simple Mobile, Tracfone, Mint Mobile, and Visible. |
| **Generic Webhook** | A URL | For technical users: sends the alert as data (JSON) to any web address you control. |
| **ntfy** | A "topic" URL, like `https://ntfy.sh/your-topic` | A free push-notification app/service. Install the free ntfy app on your phone, pick a topic name, and alerts show up as a normal push notification, like a text message from an app. |
| **Discord** | A Discord webhook URL | Alerts get posted into a channel on your Discord server — handy if you're already in a ham radio Discord community. |
| **Telegram** | A bot token + chat ID | Alerts arrive as messages from a Telegram bot you set up. |
| **Matrix** | A homeserver address + room ID + access token | Alerts get posted into a chat room on the Matrix messaging network. |

All of these are **free** to use — none of them require you (or the
person running this site) to pay for a text-messaging or notification
service.

### Testing a channel before you rely on it

Not sure if you set a channel up correctly? Don't wait for a real change
to find out! Every channel in your list has a **Send test** button next
to it. Click it, and:

- A real test message is sent through that exact channel, right now.
- The test message is intentionally **verbose** — it explains, in detail,
  what a real alert will look like when one actually arrives (which
  fields it shows, what an example change looks like), so you know
  exactly what to expect later.
- The test message respects the same length limits the real thing will
  have on that platform — for example, a text message (email-to-SMS)
  test is trimmed to fit in a single text message, just like a real
  alert would be.
- Right below the button, you'll see the result: whether it was **sent**
  successfully, **failed** (with a reason), or **timed out**.
- Once a channel successfully receives a test message, it's marked
  **✅ Verified** in your channel list, so you have a quick way to check
  at a glance which of your channels you've actually confirmed work.

### "Watch this" shortcuts on detail pages

You don't have to go find the "Add a watch" form and type things in by
hand every time. On any Amateur, GMRS, Aircraft or Ship licence detail
page, if you're signed in, you'll see small **"🔔 Watch this callsign"**
and **"🔔 Watch this FRN"** links right next to those values. Clicking
one takes you straight to the **My Watches** page with the watch type and
value already filled in for you — just pick a notification channel and
click **Add watch**.

When you click one of these from a GMRS, Aircraft or Ship page, the
Service selector arrives pre-set to that service, since that's the page
you were looking at. You can change it to **All services** before saving
if you'd rather hear about everything under that callsign or FRN — which
is usually the better choice.

## Frequently asked questions

**Why does a callsign's detail page show someone else's expired license
info in the history table?**
That's expected and intentional — FCC reissues expired callsigns as
vanity calls. The top of the page always shows the *current* holder; the
License History table below shows every holder's activity on that
callsign over time, so you can see the full lineage.

**How often is the data updated?**
Daily, from FCC's public transaction files. The exact time depends on
your instance's configuration (an operator setting, not something you
control from the UI). The 🎉 New Hams list and its counts update
automatically right along with everything else, with nothing you need
to do.

**I searched for something and got no results — is the data missing?**
This instance covers Amateur Radio, GMRS, Aircraft (Part 87), Ship
(Part 80), and Antenna Structure Registration (Tower) data. Other FCC ULS
services (commercial land mobile, broadcast, microwave, etc.) aren't
included. Double-check spelling/partial terms, or try the dedicated
browse pages with filters instead of the home page search box.

**I don't understand what a code/abbreviation on a page means — where do
I look?**
Hover your mouse over it (or tap-and-hold on mobile) for a quick tooltip,
look for a plain-language explanation in parentheses right next to it, or
visit the full **Field Definitions** page linked in the footer for an
exhaustive reference.

**I just got my callsign — will I show up in the "New Hams" celebration
list?**
Yes, automatically, as long as this is genuinely the very first amateur
license the FCC has ever recorded for your FRN — no action needed on
your part. It'll appear the day after the FCC's daily file that includes
your grant is processed by this site, and it stays on the list for 10
days.

**I created a watch but haven't gotten an alert — is something wrong?**
First, try the **Send test** button on that channel to confirm it's
actually working (see above) — that's the fastest way to rule out a
setup problem. If the test succeeds but you still haven't gotten a real
alert, it likely just means nothing has changed yet for what you're
watching. If the test itself fails or times out, your instance's SMTP
relay may not be configured yet, which would prevent email and
email-to-sms delivery specifically (webhook-based channels like ntfy/
Discord/Telegram/Matrix/generic webhook don't depend on SMTP). Check with
your operator.

**I'm not sure how to find my FRN.**
Your FRN (FCC Registration Number) is issued when you first register
with the FCC through their CORES system, before you're granted a
callsign. It's usually a 10-digit number. If you've already registered
but can't find it, check the confirmation email/paperwork from your
CORES registration, or ask whoever helped you register (like an Elmer,
VE, or radio club).
