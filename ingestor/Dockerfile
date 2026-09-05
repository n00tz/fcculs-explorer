# Ingestor service: downloads FCC daily/weekly ULS files, parses, diffs,
# and upserts into Postgres, on a daily APScheduler-driven cron.
FROM docker.io/library/python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./

RUN chmod -R a+rX /app

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser
USER appuser

# No exposed port -- this is a background scheduler process, not a server.
# `--bootstrap` (one-time complete load) and `--run-once` (single daily
# run) are available as alternate entrypoints; see scheduler.py.
CMD ["python", "scheduler.py"]
