"""Downloader for FCC ULS public data files.

Verified working host/paths (see docs/fcc-data-reference.md, 2026-09-05):
  https://data.fcc.gov/download/pub/uls/complete/{l_amat,r_tower}.zip
  https://data.fcc.gov/download/pub/uls/daily/{l_am,r_tow}_{dow}.zip

No authentication required. Applies basic retry/backoff to be a good
citizen even though no rate limiting was observed during verification.
"""
import io
import logging
import time
import zipfile
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
