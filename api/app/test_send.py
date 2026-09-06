"""Enqueues a real notification send onto the same Redis/RQ queue the
notifier service consumes, and polls briefly for the result.

The api and notifier are separate codebases/containers -- api has no
import access to notifier's sender code -- so the job is enqueued by
*string* path (`app.jobs.send_test_message`) rather than an imported
function reference. This mirrors how `notifier/app/dispatch.py` enqueues
`send_delivery` within its own process (by reference there, since it's the
same codebase); here it must be by string since only the notifier worker
process has `app.jobs` importable. `FCCULS_QUEUE_NAME` on both services
must match (see .env.example) for this to reach the right queue.

Uses the plain sync `redis`/`rq` clients (not the `redis.asyncio` client
`ratelimit.py` uses) since `rq`'s `Queue`/`Job` APIs are synchronous; this
endpoint is low-volume and rate-limited, so a short blocking call from an
async route is an acceptable tradeoff over adding a second Redis client
flavor's worth of complexity.
"""
import time

import redis as redis_sync
from rq import Queue
from rq.job import Job

from .config import settings

_TEST_SEND_JOB_PATH = "app.jobs.send_test_message"

_redis_sync: redis_sync.Redis | None = None


def _get_sync_redis() -> redis_sync.Redis:
    global _redis_sync
    if _redis_sync is None:
        _redis_sync = redis_sync.from_url(settings.redis_url)
    return _redis_sync


def enqueue_and_wait_for_test_send(channel_id: int) -> dict:
    """Enqueue a test-send job for `channel_id` and poll for its result for
    up to `settings.test_send_poll_timeout_seconds`. Returns
    {"status": "sent"|"failed"|"timeout", "detail": str}."""
    conn = _get_sync_redis()
    queue = Queue(settings.queue_name, connection=conn)
    job = queue.enqueue(_TEST_SEND_JOB_PATH, channel_id, job_timeout=30)

    deadline = time.monotonic() + settings.test_send_poll_timeout_seconds
    while time.monotonic() < deadline:
        job = Job.fetch(job.id, connection=conn)
        if job.is_finished:
            return {"status": "sent", "detail": "Test message sent successfully."}
        if job.is_failed:
            detail = "Delivery failed."
            if job.exc_info:
                # Last line of the traceback is normally the exception message.
                detail = job.exc_info.strip().splitlines()[-1]
            return {"status": "failed", "detail": detail}
        time.sleep(0.25)

    return {
        "status": "timeout",
        "detail": "Still waiting on delivery -- it may still arrive; check the channel's logs/inbox.",
    }
