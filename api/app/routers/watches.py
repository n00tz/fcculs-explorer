"""Watch CRUD -- a user subscribes a callsign or ULS/ASR ID to a
notification channel; the notifier worker matches new change_events
against active watches and enqueues deliveries."""
from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection
from pydantic import BaseModel

from ..db import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api/watches", tags=["watches"])

ALLOWED_SUBJECT_TYPES = {"callsign", "uls_id", "asr_registration_number"}

# Kept in sync with channels.py's MAX_CHANNELS_PER_USER -- see that file
# for the rationale (a secondary throttle on top of URL-safety checks).
MAX_WATCHES_PER_USER = 50


class WatchCreate(BaseModel):
    subject_type: str
    subject_value: str
    channel_id: int


@router.get("")
async def list_watches(user: dict = Depends(get_current_user), conn: AsyncConnection = Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT w.id, w.subject_type, w.subject_value, w.channel_id, w.is_active, w.created_at,
                   c.channel_type, c.label
            FROM watches w
            JOIN notification_channels c ON c.id = w.channel_id
            WHERE w.user_id = %s
            ORDER BY w.id
            """,
            (user["id"],),
        )
        rows = await cur.fetchall()
    return {"watches": rows}


@router.post("", status_code=201)
async def create_watch(
    body: WatchCreate, user: dict = Depends(get_current_user), conn: AsyncConnection = Depends(get_db)
):
    if body.subject_type not in ALLOWED_SUBJECT_TYPES:
        raise HTTPException(status_code=400, detail=f"subject_type must be one of {sorted(ALLOWED_SUBJECT_TYPES)}")

    async with conn.cursor() as cur:
        await cur.execute("SELECT count(*) AS total FROM watches WHERE user_id = %s", (user["id"],))
        if (await cur.fetchone())["total"] >= MAX_WATCHES_PER_USER:
            raise HTTPException(status_code=429, detail=f"Watch limit reached ({MAX_WATCHES_PER_USER} per user)")

        await cur.execute(
            "SELECT id FROM notification_channels WHERE id = %s AND user_id = %s",
            (body.channel_id, user["id"]),
        )
        if await cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Notification channel not found")

        subject_value = body.subject_value.strip().upper()
        try:
            await cur.execute(
                """
                INSERT INTO watches (user_id, subject_type, subject_value, channel_id)
                VALUES (%s, %s, %s, %s)
                RETURNING id, subject_type, subject_value, channel_id, is_active, created_at
                """,
                (user["id"], body.subject_type, subject_value, body.channel_id),
            )
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise HTTPException(status_code=409, detail="Watch already exists for this subject/channel")
            raise
        row = await cur.fetchone()
    await conn.commit()
    return row


@router.delete("/{watch_id}", status_code=204)
async def delete_watch(
    watch_id: int, user: dict = Depends(get_current_user), conn: AsyncConnection = Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM watches WHERE id = %s AND user_id = %s", (watch_id, user["id"]))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Watch not found")
    await conn.commit()
