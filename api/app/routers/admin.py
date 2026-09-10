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
from datetime import datetime, timezone

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

# Canonical service list (mirrors ingestor/schemas.py's SERVICES and
# watches.py's ALLOWED_SERVICES) so the ops-summary endpoint always reports
# a row for every service, even one that has never successfully ingested.
OPS_SERVICES = ["amateur", "tower", "gmrs", "aircraft", "ship"]


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


# --- Operations-at-a-glance overview ----------------------------------------
#
# Motivated by a real false alarm: because ingest_runs only gets a new row
# when there's actually something to ingest, a genuinely quiet FCC
# publishing period and a silently dead poller loop are indistinguishable
# from the database alone -- diagnosing that gap required a from-scratch
# log/DB investigation. This endpoint answers, in one round trip, whether
# each moving part (poller, ingestion, signups, notifications) is still
# operating, using heartbeats (db/011_ops_heartbeats.sql) recorded
# unconditionally by the ingestor/notifier loops every cycle, so heartbeat
# staleness alone means "the loop stopped", distinct from "found nothing
# to do".

def _heartbeat_state(age_seconds: float | None, ok_seconds: float, stale_seconds: float) -> str:
    """Classify heartbeat age into ok/stale/down/unknown.

    `unknown` (never recorded, e.g. right after a fresh migration/first
    deploy before the loop has ticked once) is deliberately distinct from
    `down` (was recording, has since gone silent) -- the former isn't
    evidence of a problem.
    """
    if age_seconds is None:
        return "unknown"
    if age_seconds <= ok_seconds:
        return "ok"
    if age_seconds <= stale_seconds:
        return "stale"
    return "down"


@router.get("/ops-summary")
async def ops_summary(
    _: None = Depends(get_current_admin),
    conn: AsyncConnection = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    async with conn.cursor() as cur:
        # --- Heartbeats -----------------------------------------------------
        await cur.execute(
            "SELECT service, last_run_at, detail FROM service_heartbeats "
            "WHERE service IN ('ingestor-poll', 'notifier-dispatch')"
        )
        heartbeats = {r["service"]: r async for r in cur}

        def hb_age_seconds(service: str) -> float | None:
            row = heartbeats.get(service)
            if row is None:
                return None
            return (now - row["last_run_at"]).total_seconds()

        ingest_hb_age = hb_age_seconds("ingestor-poll")
        dispatch_hb_age = hb_age_seconds("notifier-dispatch")

        ingest_poll_seconds = settings.ingest_poll_minutes * 60
        ingest_state = _heartbeat_state(ingest_hb_age, ingest_poll_seconds * 3, ingest_poll_seconds * 12)
        dispatch_state = _heartbeat_state(
            dispatch_hb_age, settings.dispatch_interval_seconds * 5, settings.dispatch_interval_seconds * 12
        )

        # --- Per-service ingest status ---------------------------------------
        await cur.execute(
            """
            SELECT DISTINCT ON (service)
                service, data_date, ingested_at, status, rows_ingested, changes_recorded
            FROM ingest_runs
            ORDER BY service, data_date DESC
            """
        )
        latest_by_service = {r["service"]: r async for r in cur}
        ingest_services = []
        for service in OPS_SERVICES:
            row = latest_by_service.get(service)
            ingest_services.append({
                "service": service,
                "last_data_date": row["data_date"] if row else None,
                "last_ingested_at": row["ingested_at"] if row else None,
                "status": row["status"] if row else None,
                "rows_ingested": row["rows_ingested"] if row else None,
                "changes_recorded": row["changes_recorded"] if row else None,
            })

        # --- New Hams / change activity ---------------------------------------
        await cur.execute(
            """
            SELECT count(*) AS c, max(effective_date) AS last_date
            FROM change_events
            WHERE is_new_operator AND effective_date >= (%(now)s::date - INTERVAL '7 days')
            """,
            {"now": now},
        )
        new_hams = await cur.fetchone()

        # --- Signups -----------------------------------------------------------
        await cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE created_at >= %(now)s - INTERVAL '24 hours') AS last_24h,
                count(*) FILTER (WHERE created_at >= %(now)s - INTERVAL '7 days') AS last_7_days,
                max(created_at) AS most_recent_at
            FROM users
            """,
            {"now": now},
        )
        signups = await cur.fetchone()

        # --- Notifications -------------------------------------------------------
        await cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE status = 'pending') AS pending,
                count(*) FILTER (WHERE status = 'sent' AND sent_at >= %(now)s - INTERVAL '24 hours') AS sent_last_24h,
                count(*) FILTER (WHERE status = 'failed' AND created_at >= %(now)s - INTERVAL '24 hours') AS failed_last_24h,
                max(sent_at) FILTER (WHERE status = 'sent') AS last_sent_at
            FROM notification_deliveries
            """,
            {"now": now},
        )
        notifications = await cur.fetchone()

        await cur.execute(
            "SELECT last_error, created_at FROM notification_deliveries "
            "WHERE status = 'failed' ORDER BY created_at DESC LIMIT 1"
        )
        last_failure = await cur.fetchone()

        # --- Complete dumps ----------------------------------------------------
        await cur.execute(
            "SELECT service, filename, published_at FROM complete_dumps ORDER BY service"
        )
        complete_dumps = [r async for r in cur]

    return {
        "generated_at": now,
        "ingest": {
            "heartbeat_at": heartbeats.get("ingestor-poll", {}).get("last_run_at"),
            "heartbeat_age_seconds": ingest_hb_age,
            "heartbeat_state": ingest_state,
            "heartbeat_detail": heartbeats.get("ingestor-poll", {}).get("detail"),
            "services": ingest_services,
        },
        "new_hams": {
            "last_7_days": new_hams["c"],
            "last_grant_date": new_hams["last_date"],
            "note": (
                "A quiet stretch here is normal on weekends/holidays -- check "
                "the ingest heartbeat above for whether files are actually "
                "being processed."
            ),
        },
        "signups": {
            "last_24h": signups["last_24h"],
            "last_7_days": signups["last_7_days"],
            "most_recent_at": signups["most_recent_at"],
        },
        "notifications": {
            "dispatch_heartbeat_at": heartbeats.get("notifier-dispatch", {}).get("last_run_at"),
            "dispatch_heartbeat_age_seconds": dispatch_hb_age,
            "dispatch_heartbeat_state": dispatch_state,
            "pending": notifications["pending"],
            "sent_last_24h": notifications["sent_last_24h"],
            "failed_last_24h": notifications["failed_last_24h"],
            "last_sent_at": notifications["last_sent_at"],
            "last_failure": last_failure,
        },
        "complete_dumps": complete_dumps,
    }
