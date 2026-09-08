"""Polling scheduler entrypoint for the ingestor container.

Polls FCC every ~15 minutes (APScheduler interval job) and ingests every
daily transaction file not yet loaded, for each service.

Why polling and not a daily cron:
  This used to run once a day at 13:30 UTC. FCC's publication times are not
  dependable enough for that -- tower lands around 05:00 UTC and
  amateur/GMRS around 12:00 UTC, and individual files have been observed
  anywhere in between. A single daily run means data published at 12:00 UTC
  waits ~1.5 h, and data published even slightly LATE (say 14:00 UTC) waits
  until 13:30 the NEXT day -- roughly 24 hours. Polling collapses that worst
  case to one poll interval. Note this is a LATENCY improvement, not a
  correctness fix: the catch-up loop below already recovered missed days on
  its own, within FCC's rolling seven-day window.

Why this is a catch-up loop and not "fetch today's file":
  FCC's daily files are named ONLY by weekday (`l_am_mon.zip`) and are
  rotated in place weekly -- each is overwritten roughly 12:00 UTC the day
  AFTER the weekday it is named for. So "today's weekday" file does not
  contain today's data; until FCC publishes it tomorrow, it still holds
  data from a WEEK ago. Naively fetching it (as this scheduler originally
  did) therefore re-ingested week-old transactions on every run, while the
  days actually published in between were never picked up at all. Any day
  the ingestor didn't run also became a permanent hole once FCC rotated
  that weekday's file.

  Instead, each run resolves the real calendar date each weekday file
  covers from its publication timestamp (see
  downloader.resolve_daily_data_date), and ingests -- oldest first -- every
  date not already recorded in the `ingest_runs` table. That makes the job
  self-healing (a missed day is picked up automatically on the next run, as
  long as it is still inside FCC's rolling 7-day window) and idempotent (an
  already-ingested date is skipped, so re-running can never double-count).
  That dedupe-by-real-data-date contract is exactly what makes it safe to
  call this 96 times a day instead of once.

How a poll stays cheap (see index_scraper.py):
  A full per-file sweep is 35 HEAD requests (5 services x 7 weekday files),
  which at a 15-minute interval would be ~3,360 requests/day against a
  government server. So each poll instead reads FCC's directory listing in
  ONE conditional request -- usually a 304 with no body -- and only falls
  back to HEADing the specific files backing dates it is still waiting for.
  Steady state is one request per poll; the naive alternative was 96x that.

  The listing alone is not sufficient: it is a static index.html regenerated
  on its own schedule and has been observed describing files published over
  two hours earlier. Hence the hybrid -- the listing is a cheap trigger, and
  targeted HEADs are the authority for anything actually outstanding.

A bootstrap "complete" load (for first-time setup / disaster recovery) is
available via `bootstrap_all()` and can be invoked manually (e.g.
`python scheduler.py --bootstrap`) rather than running on the poll
schedule, since it's a much larger download not needed on every run. The
documented first-run sequence is `--bootstrap` followed by `--catch-up`,
which fills in every daily increment published since the weekly dump was
cut (see the README's "Bootstrapping and catching up" section).
"""
import argparse
import hashlib
import logging
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

import index_scraper
from db import (
    ingest_advisory_lock,
    ingested_data_dates,
    latest_complete_dumps,
    record_complete_dump,
    record_ingest_run,
)
from downloader import (
    COMPLETE_FILES,
    DAILY_PREFIXES,
    DAYS_OF_WEEK,
    download_complete,
    download_daily,
    extract_zip,
    head_daily,
    read_archive_counts,
    resolve_daily_data_date,
)
from ingest import ingest_file
from schemas import SERVICES

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("FCCULS_DATABASE_URL", "******localhost:5432/fcculs")

# How often to check FCC for new files. 15 minutes bounds the worst-case
# publication-to-ingest latency at that interval, versus roughly 24 hours
# under the daily cron this replaced.
POLL_MINUTES = int(os.environ.get("FCCULS_INGEST_POLL_MINUTES", "15"))
# How often to ignore the cheap "directory listing unchanged" fast path and
# re-check every file directly. Covers the case where FCC re-publishes an
# older weekday file without the static listing reflecting it yet.
FULL_SWEEP_MINUTES = int(os.environ.get("FCCULS_INGEST_FULL_SWEEP_MINUTES", "60"))

MATERIALIZED_VIEWS = ["identity_by_frn", "towers_by_site", "entities_by_address"]

# FCC keeps only a rolling seven weekday files, so nothing older than this can
# be recovered from the daily feed -- a longer gap needs a fresh --bootstrap.
DAILY_WINDOW_DAYS = 7

# Consecutive-failure backoff. An FCC outage would otherwise produce 96
# failed sweeps a day, each already retrying 3-4 times internally.
MAX_BACKOFF_POLLS = 16

# Idle polls log at DEBUG so 96 runs/day don't drown the journal; this
# heartbeat keeps "quiet" distinguishable from "hung" at INFO level.
HEARTBEAT_SECONDS = 3600


def _refresh_materialized_views(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for view in MATERIALIZED_VIEWS:
            cur.execute(f"REFRESH MATERIALIZED VIEW {view}")
    conn.commit()
    logger.info("refreshed materialized views: %s", ", ".join(MATERIALIZED_VIEWS))


def discover_available_days(service: str, listing=None, only_days=None) -> list:
    """Resolve what real calendar date each of a service's seven weekday
    files currently holds.

    Returns [(day_of_week, data_date, last_modified), ...] sorted oldest
    data_date first. `data_date` is None for a file whose publication
    timestamp is missing/unparseable -- the caller resolves those after
    download, from the archive's own `counts` member, rather than skipping
    them permanently as this used to.

    `listing` is an optional pre-fetched index_scraper.Listing. When given,
    a file's metadata is read from it instead of spending a HEAD request --
    turning a 7-request-per-service sweep into zero. Files absent from the
    listing still fall back to a real HEAD, so a stale or partial listing
    degrades performance, never correctness.

    `only_days` limits the HEAD fallback to specific weekdays, which is how
    the poll loop checks just the files backing dates it is still waiting
    for instead of re-checking all seven.
    """
    prefix = DAILY_PREFIXES[service]
    available = []
    for dow in DAYS_OF_WEEK:
        meta = None
        if listing is not None:
            entry = listing.get(f"{prefix}_{dow}.zip")
            if entry is not None:
                meta = index_scraper.entry_to_head_meta(entry)
        if meta is None:
            if only_days is not None and dow not in only_days:
                continue
            try:
                meta = head_daily(service, dow)
            except Exception as exc:  # network/HTTP failure on one weekday file
                logger.warning("could not HEAD %s daily file for %s: %s", service, dow, exc)
                continue

        data_date = resolve_daily_data_date(dow, meta["last_modified"])
        if data_date is None:
            # Not skipped: the archive's `counts` member carries a "File
            # Creation Date" that matches Last-Modified exactly, so the file
            # can still be dated after download. Skipping here (the previous
            # behaviour) made such a file invisible forever.
            logger.info(
                "%s daily file for %s has no usable publication timestamp; "
                "will date it from the archive's `counts` member after download",
                service, dow,
            )
        available.append((dow, data_date, meta["last_modified"]))
    # None sorts last: dateable files are ingested oldest-first as before,
    # and the undateable stragglers are resolved afterwards.
    available.sort(key=lambda item: (item[1] is None, item[1] or date.min))
    return available


def resolve_services(names: list[str] | None) -> dict:
    """Resolve a list of --service arguments into the record-type maps to act on.

    Returns every service when nothing is specified, so existing invocations
    (and the scheduled daily job) are unchanged. Unknown names fail loudly
    rather than silently ingesting nothing, which would otherwise look like a
    successful no-op run.
    """
    if not names:
        return dict(SERVICES)
    unknown = [n for n in names if n not in SERVICES]
    if unknown:
        raise SystemExit(
            f"unknown service(s): {', '.join(sorted(unknown))}. "
            f"Valid choices: {', '.join(sorted(SERVICES))}"
        )
    return {n: SERVICES[n] for n in names}


def run_daily_job(run_date: date | None = None, max_days: int | None = None,
                  services: list[str] | None = None, listing=None,
                  only_days: dict | None = None) -> dict:
    """Catch up every not-yet-ingested daily transaction file for every
    service, oldest first.

    Safe to re-run at any frequency: each (service, real data date) is
    recorded in `ingest_runs` and skipped if already loaded, and the
    underlying ingestion is upsert-based/idempotent regardless. That
    contract is what lets the poll loop call this every 15 minutes.

    Holds a Postgres advisory lock for the duration and returns immediately
    if another ingest already holds it -- see db.ingest_advisory_lock for
    why (duplicate change_events become duplicate user alerts).

    `listing` and `only_days` are the poll loop's cost optimisations and are
    passed straight through to discover_available_days(); both default to
    the original behaviour of checking every weekday file directly.
    """
    run_date = run_date or datetime.now(timezone.utc).date()
    window_days = max_days if max_days is not None else DAILY_WINDOW_DAYS
    earliest = run_date - timedelta(days=window_days)

    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    summary = {}
    ingested_any = False
    try:
        with ingest_advisory_lock(conn) as acquired:
            if not acquired:
                logger.info(
                    "another ingest is already running (advisory lock held); "
                    "skipping this pass -- it will be retried on the next poll"
                )
                return summary

            for service, record_types in resolve_services(services).items():
                service_days = only_days.get(service) if only_days else None
                if only_days is not None and not service_days:
                    continue
                available = discover_available_days(
                    service, listing=listing, only_days=service_days
                )
                if not available:
                    logger.warning("no daily files found for %s", service)
                    continue

                done = ingested_data_dates(conn, service, earliest)
                pending = [
                    (dow, data_date, last_modified)
                    for dow, data_date, last_modified in available
                    # An undateable file (data_date None) is always a
                    # candidate: whether it has already been ingested can
                    # only be decided once its `counts` member dates it.
                    if data_date is None or (data_date >= earliest and data_date not in done)
                ]
                if not pending:
                    logger.info(
                        "%s: nothing to do -- all %d available day(s) already ingested",
                        service, len(available),
                    )
                    continue

                logger.info(
                    "%s: %d day(s) to ingest: %s",
                    service, len(pending),
                    ", ".join(str(d) if d else "<undated>" for _, d, _ in pending),
                )

                for dow, data_date, last_modified in pending:
                    result = _ingest_one_day(
                        conn, service, record_types, dow, data_date, last_modified,
                        done=done, earliest=earliest, summary=summary,
                    )
                    if result:
                        ingested_any = True

            if ingested_any:
                _refresh_materialized_views(conn)
            else:
                logger.debug("no new daily files ingested; skipping materialized view refresh")
    finally:
        conn.close()

    logger.info("daily ingest job complete (run date %s): %d file result(s)", run_date, len(summary))
    return summary


def _ingest_one_day(conn, service, record_types, dow, data_date, last_modified,
                    done, earliest, summary) -> bool:
    """Download, ingest and record one service-day. Returns True if
    anything was actually ingested.

    Each day is downloaded, ingested and recorded in its own temp dir so a
    failure partway through a catch-up leaves the earlier days durably
    recorded (and therefore skipped on the next run) instead of forcing the
    whole range to be redone.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        logger.info(
            "downloading %s daily file for %s (data date %s)",
            service, dow, data_date or "<to be determined from archive>",
        )
        content = download_daily(service, dow)
        content_sha256 = hashlib.sha256(content).hexdigest()
        counts = read_archive_counts(content)

        if data_date is None:
            # Fallback path: FCC gave us no usable Last-Modified, so date
            # the file from its own "File Creation Date", which matches
            # Last-Modified exactly when both are present.
            data_date = resolve_daily_data_date(dow, counts.created_at)
            if data_date is None:
                logger.warning(
                    "%s %s: no Last-Modified AND no usable `counts` creation date; "
                    "cannot determine which day this file covers, skipping",
                    service, dow,
                )
                return False
            logger.info(
                "%s %s: dated %s from the archive's `counts` member", service, dow, data_date
            )
            if data_date < earliest or data_date in done:
                logger.info(
                    "%s %s: resolved to %s, which is already ingested or outside the "
                    "window; skipping", service, dow, data_date,
                )
                return False
            last_modified = last_modified or counts.created_at

        extracted = extract_zip(content, tmp_path / f"{service}_{dow}")
        extracted_names = {p.name: p for p in extracted}

        source_file = f"{service}_{dow}.zip"
        day_rows = 0
        day_changes = 0
        parsed_rows = {}
        for filename, record_def in record_types.items():
            path = extracted_names.get(filename)
            if path is None:
                # Normal and frequent: weekend/holiday archives are a
                # 212-byte zip containing only `counts` and no .dat members
                # at all. Recording the day with zero rows is what stops it
                # being retried on every poll forever.
                logger.info(
                    "%s not present in %s daily archive for %s, skipping",
                    filename, service, dow,
                )
                continue
            result = ingest_file(
                conn, path, record_def,
                source_file=source_file,
                # The file's REAL data date, not the run date -- so
                # change_events (and therefore the New Hams window) reflect
                # when FCC actually processed the transaction, and a
                # catch-up of older days can never masquerade as today's
                # activity.
                effective_date=data_date,
                generate_diffs=True,
            )
            summary[f"{service}/{data_date}/{filename}"] = result
            parsed_rows[filename] = result.get("rows", 0)
            day_rows += result.get("rows", 0)
            day_changes += result.get("changes", 0)

    status = _verify_against_counts(service, dow, data_date, parsed_rows, counts)

    record_ingest_run(
        conn,
        service=service,
        day_of_week=dow,
        data_date=data_date,
        source_file=source_file,
        last_modified=last_modified,
        content_sha256=content_sha256,
        rows_ingested=day_rows,
        changes_recorded=day_changes,
        status=status,
    )
    logger.info(
        "%s %s (%s): %d rows, %d changes, status=%s -- recorded in ingest_runs",
        service, data_date, dow, day_rows, day_changes, status,
    )
    return True


def _verify_against_counts(service, dow, data_date, parsed_rows: dict, counts) -> str:
    """Compare what we parsed against FCC's own declared row counts.

    Every archive ships a `counts` member stating how many rows FCC wrote
    to each `.dat` file. Verified to match this project's ingestion exactly
    for two different services (amateur 2026-09-01 = 5,691 rows; ship
    2026-09-02 = 219), so a mismatch is real signal, not noise.

    Returns the status to record: 'success', or 'partial' on a mismatch.

    A mismatch is deliberately NOT a hard failure. Known FCC quirks -- the
    embedded newlines in Ship's SV.dat, unescaped '|' characters in
    free-text fields (both documented in docs/fcc-data-reference.md) -- are
    exactly what this is meant to surface, and refusing to ingest a file
    because a handful of rows are malformed would be far worse than
    ingesting it and flagging it loudly.

    Only files this project actually ingests are compared: FCC's own
    trailing "N total" line counts record types we deliberately skip
    (CO/SC/LA/SF), so comparing against that would report a permanent
    false mismatch.
    """
    if not counts.rows:
        logger.debug(
            "%s %s: no usable `counts` member; integrity check skipped", service, data_date
        )
        return "success"

    mismatches = []
    for filename, actual in parsed_rows.items():
        expected = counts.rows.get(filename)
        if expected is None:
            continue
        if expected != actual:
            mismatches.append(f"{filename}: FCC says {expected}, parsed {actual}")

    if mismatches:
        logger.warning(
            "%s %s (%s): ROW COUNT MISMATCH against FCC's own `counts` file -- %s. "
            "Data was still ingested; run recorded as 'partial' so it is visible "
            "in --status rather than silently accepted.",
            service, data_date, dow, "; ".join(mismatches),
        )
        return "partial"

    logger.debug(
        "%s %s: row counts match FCC's `counts` file for %d file(s)",
        service, data_date, len(parsed_rows),
    )
    return "success"


class PollState:
    """Mutable state carried between polls.

    Held in an object rather than module globals so tests can drive the
    backoff and full-sweep logic deterministically instead of reaching into
    module state (and leaking it between test cases).
    """

    def __init__(self):
        self.listing_last_modified = None
        self.consecutive_failures = 0
        self.skip_polls_remaining = 0
        self.last_full_sweep = None
        self.last_heartbeat = None
        self.polls_since_heartbeat = 0
        self.ingests_since_heartbeat = 0

    def record_failure(self) -> int:
        """Back off exponentially, capped. Returns how many polls to skip."""
        self.consecutive_failures += 1
        self.skip_polls_remaining = min(2 ** self.consecutive_failures, MAX_BACKOFF_POLLS)
        return self.skip_polls_remaining

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.skip_polls_remaining = 0


POLL_STATE = PollState()


def outstanding_dates(conn, services: dict, run_date: date, window_days: int) -> dict:
    """Which weekday files each service is still waiting for.

    Pure database work, no network: for each service, the dates inside FCC's
    rolling window that have no successful ingest_runs row yet, mapped back
    to the weekday-named file that would carry them. This is what lets a
    poll HEAD five files instead of thirty-five.
    """
    earliest = run_date - timedelta(days=window_days)
    result = {}
    for service in services:
        done = ingested_data_dates(conn, service, earliest)
        missing_days = set()
        # Yesterday backwards: today's file is not published until tomorrow,
        # so it is never outstanding.
        for delta in range(1, window_days + 1):
            candidate = run_date - timedelta(days=delta)
            if candidate not in done:
                missing_days.add(DAYS_OF_WEEK[candidate.weekday()])
        result[service] = missing_days
    return result


def run_poll_cycle(state: PollState | None = None, services: list[str] | None = None,
                   now: datetime | None = None) -> dict:
    """One poll: cheaply decide whether FCC has anything new, and ingest it.

    The cost model is the whole point (see this module's docstring):

      * caught up, listing unchanged  -> 1 request, a 304 with no body
      * waiting on a day              -> 1 request + one HEAD per missing file
      * naive per-file sweep          -> 35 requests, 96 times a day

    Correctness never rests on the 304. If the listing is unavailable,
    stale, or FCC stops honouring conditional requests entirely, this
    degrades to the original full sweep -- `ingest_runs` remains the only
    thing that decides what has actually been ingested.
    """
    state = state or POLL_STATE
    now = now or datetime.now(timezone.utc)
    state.polls_since_heartbeat += 1

    if state.skip_polls_remaining > 0:
        state.skip_polls_remaining -= 1
        logger.debug(
            "backing off after %d consecutive failure(s); %d poll(s) still to skip",
            state.consecutive_failures, state.skip_polls_remaining,
        )
        _maybe_heartbeat(state, now)
        return {}

    try:
        due_for_sweep = (
            state.last_full_sweep is None
            or (now - state.last_full_sweep) >= timedelta(minutes=FULL_SWEEP_MINUTES)
        )

        listing = index_scraper.fetch_listing(
            "daily",
            # A full sweep deliberately drops the conditional header so FCC
            # returns the current listing even if it hasn't changed.
            if_modified_since=None if due_for_sweep else state.listing_last_modified,
        )
        listing_changed = listing is not None
        if listing is not None and listing.listing_last_modified:
            state.listing_last_modified = listing.listing_last_modified

        conn = psycopg.connect(DATABASE_URL, autocommit=False)
        try:
            resolved = resolve_services(services)
            missing = outstanding_dates(conn, resolved, now.date(), DAILY_WINDOW_DAYS)
        finally:
            conn.close()

        anything_outstanding = any(missing.values())

        if not listing_changed and not anything_outstanding and not due_for_sweep:
            # Steady state: fully caught up and FCC hasn't republished the
            # listing. One conditional request, zero bytes, nothing to do.
            logger.debug("poll: caught up, directory listing unchanged (304); nothing to do")
            state.record_success()
            _maybe_heartbeat(state, now)
            return {}

        if due_for_sweep:
            logger.debug("poll: full sweep due (every %d min)", FULL_SWEEP_MINUTES)
            only_days = None
        else:
            # Hybrid: the static listing has been observed lagging real
            # publication by over two hours, so anything we're actively
            # waiting for is confirmed with a real HEAD rather than trusted
            # to appear in the listing on time.
            only_days = missing

        summary = run_daily_job(
            services=services,
            listing=listing,
            only_days=only_days,
        )
        if due_for_sweep:
            state.last_full_sweep = now
        if summary:
            state.ingests_since_heartbeat += 1
        state.record_success()
        _maybe_heartbeat(state, now)
        return summary

    except Exception as exc:
        skip = state.record_failure()
        logger.error(
            "poll cycle failed (%d consecutive): %s -- backing off for %d poll(s) "
            "(~%d min) before retrying",
            state.consecutive_failures, exc, skip, skip * POLL_MINUTES,
            exc_info=True,
        )
        _maybe_heartbeat(state, now)
        return {}


def _maybe_heartbeat(state: PollState, now: datetime) -> None:
    """Emit a periodic INFO summary.

    Idle polls log at DEBUG, because 96 runs a day of "nothing to do" makes
    the journal useless. This keeps a healthy-but-quiet ingestor
    distinguishable from a hung one without that noise.
    """
    if state.last_heartbeat is None:
        state.last_heartbeat = now
        return
    if (now - state.last_heartbeat) < timedelta(seconds=HEARTBEAT_SECONDS):
        return
    logger.info(
        "ingest poller heartbeat: %d poll(s) in the last hour, %d resulted in ingestion, "
        "%d consecutive failure(s)",
        state.polls_since_heartbeat, state.ingests_since_heartbeat, state.consecutive_failures,
    )
    state.last_heartbeat = now
    state.polls_since_heartbeat = 0
    state.ingests_since_heartbeat = 0


def check_complete_dumps(services: list[str] | None = None) -> dict:
    """Notice when FCC publishes a new weekly complete dump.

    Report-only by design: a complete dump is ~200 MB per service and
    re-loading it is disruptive, so this logs and records the observation
    and leaves the decision to an operator (`--bootstrap --service ...`).
    """
    listing = index_scraper.fetch_listing("complete")
    if listing is None:
        return {}

    found = {}
    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    try:
        for service in resolve_services(services):
            filename = COMPLETE_FILES.get(service)
            entry = listing.get(filename) if filename else None
            if entry is None:
                continue
            is_new = record_complete_dump(
                conn, service, filename, entry.modified, entry.size
            )
            found[service] = entry
            if is_new:
                logger.info(
                    "new weekly complete dump available for %s: %s published %s (%.1f MB). "
                    "Not loaded automatically -- run `--bootstrap --service %s` if you want it.",
                    service, filename, entry.modified.strftime("%Y-%m-%d %H:%M UTC"),
                    entry.size / 1_048_576, service,
                )
    finally:
        conn.close()
    return found


def bootstrap_all(services: list[str] | None = None) -> dict:
    """One-time (or disaster-recovery) full load from the complete weekly
    dump. Diffing is disabled since every row is new on a bootstrap load.

    Note this loads ONLY the weekly snapshot; run the catch-up pass
    afterwards (`python scheduler.py --catch-up`) to apply every daily
    increment published since that snapshot was cut.

    `services` limits the load to specific services, which is how a new
    service is added to an existing deployment without re-loading (and
    briefly disrupting) data that is already live and correct.
    """
    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    summary = {}
    try:
        # Takes the same lock as the poll loop, so an operator running a
        # bootstrap can never interleave with a scheduled ingest.
        with ingest_advisory_lock(conn) as acquired:
            if not acquired:
                raise SystemExit(
                    "another ingest is currently running (advisory lock held); "
                    "wait for it to finish before bootstrapping"
                )
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                for service, record_types in resolve_services(services).items():
                    logger.info("downloading complete dump for %s", service)
                    content = download_complete(service)
                    extracted = extract_zip(content, tmp_path / service)
                    extracted_names = {p.name: p for p in extracted}

                    source_file = f"{service}_complete.zip"
                    for filename, record_def in record_types.items():
                        path = extracted_names.get(filename)
                        if path is None:
                            logger.warning("%s not present in %s complete archive, skipping", filename, service)
                            continue
                        result = ingest_file(
                            conn, path, record_def,
                            source_file=source_file, effective_date=date.today(), generate_diffs=False,
                        )
                        summary[f"{service}/{filename}"] = result

            _refresh_materialized_views(conn)
    finally:
        conn.close()

    logger.info("bootstrap load complete: %s", summary)
    return summary


def report_status(services: list[str] | None = None) -> None:
    """Print what FCC currently offers vs. what has been ingested, so an
    operator can see gaps at a glance (and confirm a catch-up worked)."""
    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    try:
        today = datetime.now(timezone.utc).date()
        earliest = today - timedelta(days=DAILY_WINDOW_DAYS)
        # One listing serves every service, so --status costs one request
        # rather than 35 HEADs.
        listing = index_scraper.fetch_listing("daily")
        if listing is None:
            print("(directory listing unavailable; falling back to per-file HEAD requests)")

        statuses = _run_statuses(conn, earliest)
        for service in resolve_services(services):
            done = ingested_data_dates(conn, service, earliest)
            print(f"\n{service}:")
            for dow, data_date, last_modified in discover_available_days(service, listing=listing):
                if data_date is None:
                    print(f"  <undated> ({dow:<3}) no usable publication timestamp  [UNKNOWN]")
                    continue
                mark = "ingested" if data_date in done else "MISSING"
                run_status = statuses.get((service, data_date))
                if run_status == "partial":
                    # Ingested, but its row counts disagreed with FCC's own
                    # `counts` file -- surfaced rather than buried.
                    mark = "PARTIAL (row count mismatch)"
                published = f"{last_modified:%Y-%m-%d %H:%M UTC}" if last_modified else "unknown"
                print(f"  {data_date} ({dow:<3}) published {published}  [{mark}]")

        dumps = latest_complete_dumps(conn)
        if dumps:
            print("\nlatest weekly complete dumps observed:")
            for service, info in sorted(dumps.items()):
                published = info["published_at"]
                stamp = f"{published:%Y-%m-%d %H:%M UTC}" if published else "unknown"
                print(f"  {service:<9} {info['filename']:<12} published {stamp}")
    finally:
        conn.close()


def _run_statuses(conn, earliest: date) -> dict:
    """Recorded status per (service, data_date), so --status can distinguish
    a clean ingest from one flagged 'partial' by the counts check."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT service, data_date, status FROM ingest_runs WHERE data_date >= %s",
            (earliest,),
        )
        return {(r[0], r[1]): r[2] for r in cur.fetchall()}


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="run a one-time full/complete load and exit")
    parser.add_argument(
        "--run-once", action="store_true",
        help="run the catch-up ingest once and exit (no scheduler)",
    )
    parser.add_argument(
        "--catch-up", action="store_true",
        help="alias for --run-once: ingest every daily file not yet loaded, oldest first",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="show which daily files FCC currently offers and which are already ingested",
    )
    parser.add_argument(
        "--service", action="append", dest="services", metavar="NAME",
        help=(
            "limit the operation to one service (repeatable, e.g. "
            "--service gmrs --service ship). Defaults to all services. "
            f"Choices: {', '.join(sorted(SERVICES))}"
        ),
    )
    parser.add_argument(
        "--max-days", type=int, default=None,
        help=f"how many days back to consider (default {DAILY_WINDOW_DAYS}, FCC's rolling window)",
    )
    args = parser.parse_args()

    if args.bootstrap:
        bootstrap_all(services=args.services)
        return
    if args.status:
        report_status(services=args.services)
        return
    if args.run_once or args.catch_up:
        run_daily_job(max_days=args.max_days, services=args.services)
        return

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_poll_cycle,
        trigger=IntervalTrigger(
            minutes=POLL_MINUTES,
            # Never hit FCC exactly on the quarter hour, and don't have
            # every redeployed instance line up with the same second.
            jitter=60,
        ),
        id="fcculs-ingest-poll",
        # A poll must never stack on top of a still-running one; combined
        # with the advisory lock this makes overlap impossible rather than
        # merely unlikely.
        max_instances=1,
        coalesce=True,
        # A tick missed during a restart is simply picked up by the next
        # one; there is nothing to make up, because what has been ingested
        # is decided by ingest_runs, not by how many ticks fired.
        misfire_grace_time=300,
    )
    scheduler.add_job(
        check_complete_dumps,
        trigger=IntervalTrigger(minutes=FULL_SWEEP_MINUTES, jitter=60),
        id="fcculs-complete-watch",
        max_instances=1,
        coalesce=True,
    )
    # Poll shortly after boot so a deploy immediately closes any gap that
    # opened while the container was down, instead of idling for a full
    # interval first.
    scheduler.add_job(
        run_poll_cycle,
        trigger="date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=60),
        id="fcculs-ingest-startup-poll",
    )
    logger.info(
        "scheduler started; polling FCC every %d min (full sweep every %d min), "
        "with a startup poll in 60s",
        POLL_MINUTES, FULL_SWEEP_MINUTES,
    )
    scheduler.start()


if __name__ == "__main__":
    main()
