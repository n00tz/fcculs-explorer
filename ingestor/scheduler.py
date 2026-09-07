"""Daily scheduler entrypoint for the ingestor container.

Runs a cron-like daily job (via APScheduler) that catches up every FCC
daily transaction file not yet ingested, for each service (amateur, tower).

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

  Instead, each run HEADs all seven weekday files per service, resolves the
  real calendar date each one covers from its Last-Modified header (see
  downloader.resolve_daily_data_date), and ingests -- oldest first -- every
  date not already recorded in the `ingest_runs` table. That makes the job
  self-healing (a missed day is picked up automatically on the next run, as
  long as it is still inside FCC's rolling 7-day window) and idempotent (an
  already-ingested date is skipped, so re-running can never double-count).

A bootstrap "complete" load (for first-time setup / disaster recovery) is
available via `bootstrap_all()` and can be invoked manually (e.g.
`python scheduler.py --bootstrap`) rather than running on the daily
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
from apscheduler.triggers.cron import CronTrigger

from db import ingested_data_dates, record_ingest_run
from downloader import (
    DAYS_OF_WEEK,
    download_complete,
    download_daily,
    extract_zip,
    head_daily,
    resolve_daily_data_date,
)
from ingest import ingest_file
from schemas import SERVICES

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("FCCULS_DATABASE_URL", "******localhost:5432/fcculs")
# FCC publishes each daily file around 12:00 UTC the day after its weekday
# (verified against real Last-Modified headers), so the default run time sits
# safely after that window. The catch-up design means an early or failed run
# is self-healing regardless -- it just picks the day up on the next pass.
DAILY_CRON_HOUR = int(os.environ.get("FCCULS_INGEST_CRON_HOUR", "13"))
DAILY_CRON_MINUTE = int(os.environ.get("FCCULS_INGEST_CRON_MINUTE", "30"))

MATERIALIZED_VIEWS = ["identity_by_frn", "towers_by_site", "entities_by_address"]

# FCC keeps only a rolling seven weekday files, so nothing older than this can
# be recovered from the daily feed -- a longer gap needs a fresh --bootstrap.
DAILY_WINDOW_DAYS = 7


def _refresh_materialized_views(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for view in MATERIALIZED_VIEWS:
            cur.execute(f"REFRESH MATERIALIZED VIEW {view}")
    conn.commit()
    logger.info("refreshed materialized views: %s", ", ".join(MATERIALIZED_VIEWS))


def discover_available_days(service: str) -> list:
    """HEAD all seven weekday files for a service and resolve what real
    calendar date each currently holds.

    Returns [(day_of_week, data_date, last_modified), ...] sorted oldest
    data_date first, skipping any file whose date could not be resolved (a
    missing/unparseable Last-Modified) rather than guessing at it.
    """
    available = []
    for dow in DAYS_OF_WEEK:
        try:
            meta = head_daily(service, dow)
        except Exception as exc:  # network/HTTP failure on one weekday file
            logger.warning("could not HEAD %s daily file for %s: %s", service, dow, exc)
            continue
        data_date = resolve_daily_data_date(dow, meta["last_modified"])
        if data_date is None:
            logger.warning(
                "%s daily file for %s has no usable Last-Modified; skipping (cannot date it)",
                service, dow,
            )
            continue
        available.append((dow, data_date, meta["last_modified"]))
    available.sort(key=lambda item: item[1])
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
                  services: list[str] | None = None) -> dict:
    """Catch up every not-yet-ingested daily transaction file for every
    service, oldest first.

    Safe to re-run at any frequency: each (service, real data date) is
    recorded in `ingest_runs` and skipped if already loaded, and the
    underlying ingestion is upsert-based/idempotent regardless.
    """
    run_date = run_date or datetime.now(timezone.utc).date()
    window_days = max_days if max_days is not None else DAILY_WINDOW_DAYS
    earliest = run_date - timedelta(days=window_days)

    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    summary = {}
    ingested_any = False
    try:
        for service, record_types in resolve_services(services).items():
            available = discover_available_days(service)
            if not available:
                logger.warning("no dateable daily files found for %s", service)
                continue

            done = ingested_data_dates(conn, service, earliest)
            pending = [
                (dow, data_date, last_modified)
                for dow, data_date, last_modified in available
                if data_date >= earliest and data_date not in done
            ]
            if not pending:
                logger.info(
                    "%s: nothing to do -- all %d available day(s) already ingested",
                    service, len(available),
                )
                continue

            logger.info(
                "%s: %d day(s) to ingest: %s",
                service, len(pending), ", ".join(str(d) for _, d, _ in pending),
            )

            for dow, data_date, last_modified in pending:
                # Each day is downloaded, ingested and recorded in its own
                # temp dir so a failure partway through a catch-up leaves the
                # earlier days durably recorded (and therefore skipped on the
                # next run) instead of forcing the whole range to be redone.
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    logger.info(
                        "downloading %s daily file for %s (data date %s)", service, dow, data_date
                    )
                    content = download_daily(service, dow)
                    content_sha256 = hashlib.sha256(content).hexdigest()
                    extracted = extract_zip(content, tmp_path / f"{service}_{dow}")
                    extracted_names = {p.name: p for p in extracted}

                    source_file = f"{service}_{dow}.zip"
                    day_rows = 0
                    day_changes = 0
                    for filename, record_def in record_types.items():
                        path = extracted_names.get(filename)
                        if path is None:
                            logger.warning(
                                "%s not present in %s daily archive, skipping", filename, service
                            )
                            continue
                        result = ingest_file(
                            conn, path, record_def,
                            source_file=source_file,
                            # The file's REAL data date, not the run date --
                            # so change_events (and therefore the New Hams
                            # window) reflect when FCC actually processed the
                            # transaction, and a catch-up of older days can
                            # never masquerade as today's activity.
                            effective_date=data_date,
                            generate_diffs=True,
                        )
                        summary[f"{service}/{data_date}/{filename}"] = result
                        day_rows += result.get("rows", 0)
                        day_changes += result.get("changes", 0)

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
                )
                ingested_any = True
                logger.info(
                    "%s %s (%s): %d rows, %d changes -- recorded in ingest_runs",
                    service, data_date, dow, day_rows, day_changes,
                )

        if ingested_any:
            _refresh_materialized_views(conn)
        else:
            logger.info("no new daily files ingested; skipping materialized view refresh")
    finally:
        conn.close()

    logger.info("daily ingest job complete (run date %s): %d file result(s)", run_date, len(summary))
    return summary


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
        for service in resolve_services(services):
            done = ingested_data_dates(conn, service, earliest)
            print(f"\n{service}:")
            for dow, data_date, last_modified in discover_available_days(service):
                mark = "ingested" if data_date in done else "MISSING"
                print(f"  {data_date} ({dow:<3}) published {last_modified:%Y-%m-%d %H:%M UTC}  [{mark}]")
    finally:
        conn.close()


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
        run_daily_job,
        trigger=CronTrigger(hour=DAILY_CRON_HOUR, minute=DAILY_CRON_MINUTE),
        id="fcculs-daily-ingest",
        misfire_grace_time=3600,
    )
    logger.info("scheduler started; daily ingest scheduled for %02d:%02d UTC", DAILY_CRON_HOUR, DAILY_CRON_MINUTE)
    scheduler.start()


if __name__ == "__main__":
    main()
