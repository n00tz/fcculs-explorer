"""Scraper for FCC's browsable directory listings.

FCC serves a directory index for both the daily and complete download
directories, e.g.:

    https://data.fcc.gov/download/pub/uls/daily/

Each row carries the filename, its publication timestamp and its exact
byte size -- i.e. everything downloader.head_daily() extracts, for every
file, in ONE request. That is what makes polling every 15 minutes viable:
a full per-file sweep is 35 HEADs (5 services x 7 weekday files), which at
96 polls/day would be ~3,360 requests against a government server. Reading
the listing instead is 1 request, and usually a 304 with no body at all.

Three behaviours of FCC's server were verified directly (2026-09-08) and
are load-bearing for the code below:

  1. `If-Modified-Since` returns 304. `If-None-Match` does NOT -- sending
     back the ETag FCC itself just issued still yields 200 plus the full
     body. Conditional requests must therefore key on Last-Modified; the
     "obvious" ETag implementation would silently transfer everything on
     every poll while appearing to work.

  2. Timestamps in the listing are US EASTERN, not UTC. `l_amat.zip` shows
     `2026-09-06 09:08:06` in the listing and `Sun, 06 Sep 2026 13:08:06
     GMT` via HEAD. They are converted with a real timezone rather than a
     fixed -4 offset: every timestamp currently on the server is summer
     time, so a hardcoded offset would pass every test written today and
     then silently misdate every file at the November DST change -- which
     can shift a file into the wrong data_date entirely.

  3. The listing is a static index.html regenerated on its own schedule,
     NOT live autoindex output. It has been observed describing files
     published over two hours earlier. So it is a cheap primary signal,
     never the sole source of truth: the scheduler still HEADs the
     specific files backing dates it is actively waiting for.

Parsing is deliberately tolerant. This is third-party HTML that we do not
control; an unrecognised row is skipped and a wholly unparseable document
returns nothing, so the caller falls back to per-file HEADs rather than
the ingestor crashing on a cosmetic upstream change.
"""
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://data.fcc.gov/download/pub/uls"

# Timestamps in FCC's directory listing are wall-clock US Eastern. Using the
# named zone (not a fixed offset) is what keeps them correct across the DST
# transitions in March and November.
FCC_TZ = ZoneInfo("America/New_York")

# Anchored on the href so a row must present a real link to be considered,
# then the timestamp and size that follow it. Rows that do not match this
# shape (the header, the <HR>, the parent-directory link, any future column
# FCC adds) are simply skipped.
_ROW_RE = re.compile(
    r'href="(?P<name>[A-Za-z0-9_\-.]+\.zip)"[^>]*>[^<]*</a>\s*'
    r"(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\s+"
    r"(?P<size>\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ListingEntry:
    """One file in a directory listing.

    `modified` is normalised to UTC so it is directly comparable with the
    Last-Modified datetimes downloader.head_daily() returns -- callers must
    never have to remember that the wire format was Eastern.
    """
    name: str
    modified: datetime
    size: int


@dataclass
class Listing:
    """A parsed directory listing plus the raw Last-Modified of the listing
    document itself, which is what the next conditional request sends."""
    entries: dict = field(default_factory=dict)
    listing_last_modified: str | None = None

    def get(self, name: str):
        return self.entries.get(name)


def parse_listing(html: str) -> dict:
    """Parse FCC's directory-index HTML into {filename: ListingEntry}.

    Rows that don't match the expected shape are skipped rather than
    raising: a partially-understood listing is still useful, and the
    scheduler treats an empty/short result as "fall back to HEADs".
    """
    entries: dict = {}
    for match in _ROW_RE.finditer(html):
        name = match.group("name")
        try:
            naive = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")
            modified = naive.replace(tzinfo=FCC_TZ).astimezone(timezone.utc)
            size = int(match.group("size"))
        except (ValueError, OverflowError) as exc:
            logger.warning("skipping unparseable listing row for %s: %s", name, exc)
            continue
        entries[name] = ListingEntry(name=name, modified=modified, size=size)
    return entries


def fetch_listing(directory: str = "daily", if_modified_since: str | None = None,
                  max_attempts: int = 3) -> Listing | None:
    """Fetch and parse a directory listing.

    Returns None when the server answers 304 (nothing changed since
    `if_modified_since`), which is the steady-state case and costs no body
    bytes at all. Returns None on persistent network failure too -- the
    caller's contract is "no listing available, use HEADs", and an FCC
    outage must not take the poll loop down.

    `if_modified_since` is the raw Last-Modified string from a previous
    call (see Listing.listing_last_modified), passed back verbatim rather
    than reformatted, so we never introduce a parsing discrepancy of our
    own into a conditional request.
    """
    url = f"{BASE_URL}/{directory.strip('/')}/"
    headers = {"Accept-Encoding": "gzip"}
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = httpx.get(url, timeout=60.0, follow_redirects=True, headers=headers)
            if resp.status_code == 304:
                logger.debug("directory listing %s unchanged (304)", directory)
                return None
            resp.raise_for_status()
            entries = parse_listing(resp.text)
            if not entries:
                logger.warning(
                    "directory listing %s parsed to zero entries (%d bytes); "
                    "treating as unavailable so callers fall back to HEAD requests",
                    directory, len(resp.content),
                )
                return None
            return Listing(
                entries=entries,
                listing_last_modified=resp.headers.get("last-modified"),
            )
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "directory listing attempt %d/%d failed for %s: %s",
                attempt, max_attempts, url, exc,
            )
            if attempt < max_attempts:
                time.sleep(3.0 * attempt)

    logger.warning("could not fetch directory listing %s: %s", directory, last_exc)
    return None


def entry_to_head_meta(entry: ListingEntry) -> dict:
    """Adapt a ListingEntry to the dict shape downloader.head_daily()
    returns, so the scheduler can use a listing row anywhere it would
    otherwise have spent a HEAD request.

    `etag` is None because the listing does not publish per-file ETags --
    and nothing in this project relies on them (FCC ignores If-None-Match
    anyway; see this module's docstring).
    """
    return {"last_modified": entry.modified, "size": entry.size, "etag": None}


def http_date(value: datetime) -> str:
    """Format a datetime as an RFC 7231 HTTP-date, for If-Modified-Since."""
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def parse_http_date(value: str) -> datetime | None:
    """Parse an HTTP-date header, returning None rather than raising on
    anything malformed."""
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
