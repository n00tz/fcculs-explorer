# Notifier service: this single image serves two roles selected by the
# compose `command:` override -- an RQ worker (default CMD, processes
# queued deliveries) and a dispatcher (`python -m app.dispatch`, matches
# new change_events to active watches and enqueues jobs; run on a loop or
# short interval by the compose command / an external timer).
FROM docker.io/library/python:3.12-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN chmod -R a+rX /app

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser
USER appuser

CMD ["python", "-m", "app.worker"]
