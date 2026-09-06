"""Redis-backed fixed-window rate limiter for abuse-prone unauthenticated
endpoints (magic-link request-link, admin login). Redis-backed rather than
in-memory so limits survive an API restart/redeploy (e.g. every
`deploy/update.sh` run) and would stay shared if the API were ever scaled
to multiple worker processes.

Uses a simple INCR + EXPIRE fixed-window counter per key -- not a
sliding-window/token-bucket algorithm, which is unnecessary precision for
this app's threat model (stop scripted abuse, not shape traffic exactly).
"""
from fastapi import HTTPException, status
from redis.asyncio import Redis

from .config import settings

_redis: Redis | None = None


def _get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None


async def enforce_rate_limit(key: str, max_requests: int, window_seconds: int) -> None:
    """Raise HTTP 429 if `key` has already been hit `max_requests` times
    within the current `window_seconds` window; otherwise record this hit."""
    redis = _get_redis()
    redis_key = f"ratelimit:{key}"
    count = await redis.incr(redis_key)
    if count == 1:
        # First hit in this window -- start the window's expiry now.
        await redis.expire(redis_key, window_seconds)
    if count > max_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
        )
