"""Dispatch loop: matches new change_events against active watches, records
pending deliveries, and enqueues an RQ job per new delivery. Intended to be
run on a short interval (e.g. every minute) by a scheduler, separate from
the RQ worker(s) that actually send messages -- keeps matching (fast, DB-
only) decoupled from sending (slow, network-bound, needs retries)."""
import logging

from redis import Redis
from rq import Queue, Retry

from .config import settings
from .db import get_connection
from .jobs import send_delivery
from .matcher import match_and_record

logger = logging.getLogger(__name__)


def run_once() -> int:
    """Match new events, enqueue jobs for newly created deliveries. Returns
    the number of deliveries enqueued."""
    conn = get_connection()
    try:
        new_delivery_ids = match_and_record(conn)
    finally:
        conn.close()

    if not new_delivery_ids:
        return 0

    redis_conn = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=redis_conn)
    for delivery_id in new_delivery_ids:
        queue.enqueue(send_delivery, delivery_id, retry=Retry(max=3, interval=[30, 120, 600]))

    logger.info("enqueued %d new notification deliveries", len(new_delivery_ids))
    return len(new_delivery_ids)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_once()
