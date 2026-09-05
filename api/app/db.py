"""Async Postgres connection pool shared across the API's request lifecycle."""
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row

from .config import settings

pool: AsyncConnectionPool | None = None


async def open_pool() -> None:
    global pool
    pool = AsyncConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        open=False,
    )
    await pool.open()


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


async def get_db():
    """FastAPI dependency yielding a connection from the pool."""
    assert pool is not None, "connection pool not initialized"
    async with pool.connection() as conn:
        yield conn
