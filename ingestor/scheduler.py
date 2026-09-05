"""Daily scheduler entrypoint for the ingestor container.

Runs a cron-like daily job (via APScheduler) that, for each service
(amateur, tower):
  1. Downloads that day's daily transaction file from data.fcc.gov.
  2. Extracts it and ingests every record-type .dat file present, diffing
     each row against current DB state and recording change_events.
  3. Refreshes the identity-grouping materialized views so newly changed
     FRN/site/address relationships are immediately reflected.

A bootstrap "complete" load (for first-time setup / disaster recovery) is
available via `bootstrap_all()` and can be invoked manually (e.g.
`python scheduler.py --bootstrap`) rather than running on the daily
schedule, since it's a much larger download not needed on every run.
"""
import argparse
import logging
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from downloader import DAYS_OF_WEEK, download_complete, download_daily, extract_zip
from ingest import ingest_file
from schemas import SERVICES

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("FCCULS_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/fcculs")
DAILY_CRON_HOUR = int(os.environ.get("FCCULS_INGEST_CRON_HOUR", "7"))
DAILY_CRON_MINUTE = int(os.environ.get("FCCULS_INGEST_CRON_MINUTE", "0"))

MATERIALIZED_VIEWS = ["identity_by_frn", "towers_by_site", "entities_by_address"]


def _refresh_materialized_views(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for view in MATERIALIZED_VIEWS:
            cur.execute(f"REFRESH MATERIALIZED VIEW {view}")
    conn.commit()
    logger.info("refreshed materialized views: %s", ", ".join(MATERIALIZED_VIEWS))


def run_daily_job(run_date: date | None = None) -> dict:
    """Download + ingest today's daily transaction file for every service.
    Safe to re-run: ingestion is upsert-based and diffing is idempotent."""
    run_date = run_date or datetime.now(timezone.utc).date()
    day_of_week = DAYS_OF_WEEK[run_date.weekday()]

    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    summary = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for service, record_types in SERVICES.items():
                logger.info("downloading daily %s file for %s", service, day_of_week)
                content = download_daily(service, day_of_week)
                extracted = extract_zip(content, tmp_path / service)
                extracted_names = {p.name: p for p in extracted}

                source_file = f"{service}_{day_of_week}.zip"
                for filename, record_def in record_types.items():
                    path = extracted_names.get(filename)
                    if path is None:
                        logger.warning("%s not present in %s daily archive, skipping", filename, service)
                        continue
                    result = ingest_file(
                        conn, path, record_def,
                        source_file=source_file, effective_date=run_date, generate_diffs=True,
                    )
                    summary[f"{service}/{filename}"] = result

        _refresh_materialized_views(conn)
    finally:
        conn.close()

    logger.info("daily ingest job complete for %s: %s", run_date, summary)
    return summary


def bootstrap_all() -> dict:
    """One-time (or disaster-recovery) full load from the complete weekly
    dump. Diffing is disabled since every row is new on a bootstrap load."""
    conn = psycopg.connect(DATABASE_URL, autocommit=False)
    summary = {}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for service, record_types in SERVICES.items():
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


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    parser = argparse.ArgumentParser()
    parser.add_argument("--bootstrap", action="store_true", help="run a one-time full/complete load and exit")
    parser.add_argument("--run-once", action="store_true", help="run today's daily job once and exit (no scheduler)")
    args = parser.parse_args()

    if args.bootstrap:
        bootstrap_all()
        return
    if args.run_once:
        run_daily_job()
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
