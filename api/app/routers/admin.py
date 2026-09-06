"""Hidden /admin panel API: superuser login + paginated user/watch
management. Not a general-purpose data-editing admin (early-version scope
per the project plan) -- limited to what's needed to operate the alerting
side of the app: see/edit/delete user accounts and their watches.

Authentication is a single process-wide password generated at API startup
and printed to the container logs (see app.admin_auth) -- there is no admin
user row, no password stored in the database, and no way to configure it
via .env. This is a deliberately narrow, low-ceremony superuser mechanism
appropriate for a single-operator self-hosted deployment, not a
multi-admin RBAC system.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from psycopg import AsyncConnection
from pydantic import BaseModel

from ..admin_auth import verify_admin_password
from ..config import settings
from ..db import get_db
from ..deps import get_current_admin
from ..pagination import Page, PageParams
from ..ratelimit import enforce_rate_limit
from ..security import create_admin_session_cookie

router = APIRouter(prefix="/api/admin", tags=["admin"])


class AdminLoginBody(BaseModel):
    password: str


@router.post("/login")
async def admin_login(body: AdminLoginBody, response: Response, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"admin-login:{client_ip}",
        settings.rate_limit_admin_login_max,
        settings.rate_limit_admin_login_window_seconds,
    )
    if not verify_admin_password(body.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")
    response.set_cookie(
        settings.admin_session_cookie_name,
        create_admin_session_cookie(),
        max_age=settings.admin_session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return {"detail": "Signed in"}


@router.post("/logout")
async def admin_logout(response: Response):
    response.delete_cookie(settings.admin_session_cookie_name)
    return {"detail": "Signed out"}


@router.get("/me")
async def admin_me(_: None = Depends(get_current_admin)):
    return {"admin": True}


# --- Users -----------------------------------------------------------------

class UserUpdate(BaseModel):
    email: str


@router.get("/users", response_model=Page)
async def list_users(
    page_params: PageParams = Depends(),
    _: None = Depends(get_current_admin),
    conn: AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute("SELECT count(*) AS total FROM users")
        total = (await cur.fetchone())["total"]

        await cur.execute(
            """
            SELECT u.id, u.email, u.created_at,
                   count(DISTINCT c.id) AS channel_count,
                   count(DISTINCT w.id) AS watch_count
            FROM users u
            LEFT JOIN notification_channels c ON c.user_id = u.id
            LEFT JOIN watches w ON w.user_id = u.id
            GROUP BY u.id
            ORDER BY u.id
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"limit": page_params.limit, "offset": page_params.offset},
        )
        rows = await cur.fetchall()
    return Page(items=rows, page=page_params.page, page_size=page_params.page_size, total=total)


@router.get("/users/{user_id}")
async def get_user(
    user_id: int, _: None = Depends(get_current_admin), conn: AsyncConnection = Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute("SELECT id, email, created_at FROM users WHERE id = %s", (user_id,))
        user = await cur.fetchone()
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")

        await cur.execute(
            "SELECT id, channel_type, label, config, is_verified, created_at FROM notification_channels WHERE user_id = %s ORDER BY id",
            (user_id,),
        )
        channels = await cur.fetchall()

        await cur.execute(
            """
            SELECT w.id, w.subject_type, w.subject_value, w.channel_id, w.is_active, w.created_at,
                   c.channel_type, c.label
            FROM watches w
            JOIN notification_channels c ON c.id = w.channel_id
            WHERE w.user_id = %s
            ORDER BY w.id
            """,
            (user_id,),
        )
        watches = await cur.fetchall()

    return {"user": user, "channels": channels, "watches": watches}


@router.patch("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdate,
    _: None = Depends(get_current_admin),
    conn: AsyncConnection = Depends(get_db),
):
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="email is required")
    async with conn.cursor() as cur:
        try:
            await cur.execute(
                "UPDATE users SET email = %s WHERE id = %s RETURNING id, email, created_at",
                (email, user_id),
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="Another user already has that email")
            raise
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="User not found")
    await conn.commit()
    return row


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: int, _: None = Depends(get_current_admin), conn: AsyncConnection = Depends(get_db)
):
    # magic_link_tokens, notification_channels, watches all have
    # ON DELETE CASCADE FKs to users.id (db/001_app_tables.sql), so this
    # cleanly removes everything belonging to the account in one statement.
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
    await conn.commit()


# --- Watches (admin-wide) ----------------------------------------------------

class WatchUpdate(BaseModel):
    subject_value: str | None = None
    is_active: bool | None = None
    channel_id: int | None = None


@router.get("/watches", response_model=Page)
async def list_all_watches(
    page_params: PageParams = Depends(),
    _: None = Depends(get_current_admin),
    conn: AsyncConnection = Depends(get_db),
):
    async with conn.cursor() as cur:
        await cur.execute("SELECT count(*) AS total FROM watches")
        total = (await cur.fetchone())["total"]

        await cur.execute(
            """
            SELECT w.id, w.user_id, u.email AS user_email, w.subject_type, w.subject_value,
                   w.channel_id, c.channel_type, c.label, w.is_active, w.created_at
            FROM watches w
            JOIN users u ON u.id = w.user_id
            JOIN notification_channels c ON c.id = w.channel_id
            ORDER BY w.id
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"limit": page_params.limit, "offset": page_params.offset},
        )
        rows = await cur.fetchall()
    return Page(items=rows, page=page_params.page, page_size=page_params.page_size, total=total)


@router.patch("/watches/{watch_id}")
async def update_watch(
    watch_id: int,
    body: WatchUpdate,
    _: None = Depends(get_current_admin),
    conn: AsyncConnection = Depends(get_db),
):
    fields = []
    params: dict = {"watch_id": watch_id}
    if body.subject_value is not None:
        fields.append("subject_value = %(subject_value)s")
        params["subject_value"] = body.subject_value.strip().upper()
    if body.is_active is not None:
        fields.append("is_active = %(is_active)s")
        params["is_active"] = body.is_active
    if body.channel_id is not None:
        fields.append("channel_id = %(channel_id)s")
        params["channel_id"] = body.channel_id
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            UPDATE watches SET {', '.join(fields)}
            WHERE id = %(watch_id)s
            RETURNING id, user_id, subject_type, subject_value, channel_id, is_active, created_at
            """,
            params,
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Watch not found")
    await conn.commit()
    return row


@router.delete("/watches/{watch_id}", status_code=204)
async def delete_watch_admin(
    watch_id: int, _: None = Depends(get_current_admin), conn: AsyncConnection = Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM watches WHERE id = %s", (watch_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Watch not found")
    await conn.commit()
