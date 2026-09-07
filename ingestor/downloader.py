"""Downloader for FCC ULS public data files.

Verified working host/paths (see docs/fcc-data-reference.md, 2026-09-05):
  https://data.fcc.gov/download/pub/uls/complete/{l_amat,r_tower}.zip
  https://data.fcc.gov/download/pub/uls/daily/{l_am,r_tow}_{dow}.zip

Daily files are named by weekday only and are rotated in place weekly --
`l_am_mon.zip` is overwritten each Tuesday with the previous Monday's
transactions (verified against real Last-Modified headers: every daily
file is published roughly 12:00 UTC the day AFTER the weekday it is named
for). Callers must therefore use resolve_daily_data_date() to learn which
calendar date a given file actually covers, rather than assuming the
weekday in the filename refers to the current week.

No authentication required. Applies basic retry/backoff to be a good
citizen even though no rate limiting was observed during verification.
"""
import io
import logging
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://data.fcc.gov/download/pub/uls"

COMPLETE_FILES = {
    "amateur": "l_amat.zip",
    "tower": "r_tower.zip",
}

DAILY_PREFIXES = {
    "amateur": "l_am",
    "tower": "r_tow",
}

DAYS_OF_WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _download_with_retry(url: str, max_attempts: int = 4, backoff_seconds: float = 5.0) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = httpx.get(url, timeout=120.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except (httpx.HTTPError,) as exc:
            last_exc = exc
            logger.warning("download attempt %d/%d failed for %s: %s", attempt, max_attempts, url, exc)
            if attempt < max_attempts:
                time.sleep(backoff_seconds * attempt)
    assert last_exc is not None
    raise last_exc


def download_complete(service: str) -> bytes:
    """Download the full weekly database dump for a service ('amateur' or 'tower')."""
    filename = COMPLETE_FILES[service]
    return _download_with_retry(f"{BASE_URL}/complete/{filename}")


def download_daily(service: str, day_of_week: str) -> bytes:
    """Download the daily transaction file for a service and day (e.g. 'mon')."""
    if day_of_week not in DAYS_OF_WEEK:
        raise ValueError(f"invalid day_of_week {day_of_week!r}, expected one of {DAYS_OF_WEEK}")
    prefix = DAILY_PREFIXES[service]
    return _download_with_retry(f"{BASE_URL}/daily/{prefix}_{day_of_week}.zip")


def head_daily(service: str, day_of_week: str) -> dict:
    """HEAD a daily file, returning its publication metadata without
    downloading the body: {"last_modified": datetime|None, "size": int|None,
    "etag": str|None}.

    Used to work out which weekday files are actually fresh (see
    resolve_daily_data_date) before spending bandwidth on them.
    """
    if day_of_week not in DAYS_OF_WEEK:
        raise ValueError(f"invalid day_of_week {day_of_week!r}, expected one of {DAYS_OF_WEEK}")
    prefix = DAILY_PREFIXES[service]
    url = f"{BASE_URL}/daily/{prefix}_{day_of_week}.zip"

    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            resp = httpx.head(url, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            raw_lm = resp.headers.get("last-modified")
            raw_len = resp.headers.get("content-length")
            return {
                "last_modified": parsedate_to_datetime(raw_lm) if raw_lm else None,
                "size": int(raw_len) if raw_len and raw_len.isdigit() else None,
                "etag": resp.headers.get("etag"),
            }
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            last_exc = exc
            logger.warning("HEAD attempt %d/3 failed for %s: %s", attempt, url, exc)
            if attempt < 3:
                time.sleep(3.0 * attempt)
    assert last_exc is not None
    raise last_exc


def resolve_daily_data_date(day_of_week: str, last_modified: datetime | None) -> date | None:
    """Work out which calendar date's transactions a `{prefix}_{dow}.zip`
    file actually contains, from the day-of-week in its name plus the
    file's Last-Modified (publication) timestamp.

    This exists because FCC's daily files are named ONLY by weekday and
    rotate in place weekly: `l_am_mon.zip` is overwritten every Tuesday
    with the previous Monday's transactions. So on any given day, six of
    the seven weekday files hold data from the current week and one still
    holds data from a week ago -- and naively fetching "today's weekday"
    file (as this scheduler originally did) reliably ingests week-old data,
    because today's file isn't published until roughly noon UTC TOMORROW.

    Algorithm: FCC publishes day D's file on day D+1, so walk backwards
    from the publication date to the first date whose weekday matches the
    file's name. Walking (rather than assuming exactly "publish date - 1
    day") keeps this correct if FCC ever publishes late -- e.g. a Monday
    file published on Wednesday after a holiday still resolves to Monday.

    Returns None if Last-Modified was missing/unparseable, so callers can
    decide how to handle an undateable file rather than silently guessing.
    """
    if day_of_week not in DAYS_OF_WEEK:
        raise ValueError(f"invalid day_of_week {day_of_week!r}, expected one of {DAYS_OF_WEEK}")
    if last_modified is None:
        return None

    target_weekday = DAYS_OF_WEEK.index(day_of_week)
    published_on = last_modified.astimezone(timezone.utc).date()
    for delta in range(0, 8):
        candidate = published_on - timedelta(days=delta)
        if candidate.weekday() == target_weekday:
            return candidate
    return None  # unreachable: any 8-day window contains every weekday


def extract_zip(content: bytes, dest_dir: Path) -> list[Path]:
    """Extract a downloaded zip's contents into dest_dir, returning extracted paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for name in zf.namelist():
            if not name.endswith(".dat"):
                continue
            target = dest_dir / name
            with zf.open(name) as src, open(target, "wb") as dst:
                dst.write(src.read())
            extracted.append(target)
    return extracted
