"""Shared FastAPI dependencies: DB connection + current-user resolution from
the signed session cookie."""
from fastapi import Depends, HTTPException, Request, status
from psycopg import AsyncConnection

from .config import settings
from .db import get_db
from .security import read_session_cookie


async def get_optional_user(
    request: Request, conn: AsyncConnection = Depends(get_db)
) -> dict | None:
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        return None
    user_id = read_session_cookie(cookie_value)
    if user_id is None:
        return None
    async with conn.cursor() as cur:
        await cur.execute("SELECT id, email FROM users WHERE id = %s", (user_id,))
        return await cur.fetchone()


async def get_current_user(user: dict | None = Depends(get_optional_user)) -> dict:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user
