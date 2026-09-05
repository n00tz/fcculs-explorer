"""RQ worker entrypoint: `python -m app.worker` -- consumes the
notifications queue and runs `send_delivery` jobs. Run one or more of these
as the `notifier` container's process; `dispatch.py` is run separately
(e.g. via a lightweight scheduler/cron) to feed the queue."""
import logging

from redis import Redis
from rq import Worker

from .config import settings

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    redis_conn = Redis.from_url(settings.redis_url)
    worker = Worker([settings.queue_name], connection=redis_conn)
    worker.work()
