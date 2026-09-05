"""Notification channel CRUD -- the delivery targets (SMTP email,
email-to-SMS gateway, generic webhook, ntfy/Discord/Telegram/Matrix presets)
a signed-in user can attach to watches."""
from fastapi import APIRouter, Depends, HTTPException
from psycopg import AsyncConnection
from psycopg.types.json import Json
from pydantic import BaseModel

from ..db import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/api/channels", tags=["channels"])

ALLOWED_CHANNEL_TYPES = {"smtp", "email_to_sms", "webhook", "ntfy", "discord", "telegram", "matrix"}


class ChannelCreate(BaseModel):
    channel_type: str
    label: str | None = None
    config: dict


@router.get("")
async def list_channels(user: dict = Depends(get_current_user), conn: AsyncConnection = Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, channel_type, label, config, is_verified, created_at FROM notification_channels WHERE user_id = %s ORDER BY id",
            (user["id"],),
        )
        rows = await cur.fetchall()
    return {"channels": rows}


@router.post("", status_code=201)
async def create_channel(
    body: ChannelCreate, user: dict = Depends(get_current_user), conn: AsyncConnection = Depends(get_db)
):
    if body.channel_type not in ALLOWED_CHANNEL_TYPES:
        raise HTTPException(status_code=400, detail=f"channel_type must be one of {sorted(ALLOWED_CHANNEL_TYPES)}")
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO notification_channels (user_id, channel_type, label, config)
            VALUES (%s, %s, %s, %s)
            RETURNING id, channel_type, label, config, is_verified, created_at
            """,
            (user["id"], body.channel_type, body.label, Json(body.config)),
        )
        row = await cur.fetchone()
    await conn.commit()
    return row


@router.delete("/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: int, user: dict = Depends(get_current_user), conn: AsyncConnection = Depends(get_db)
):
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM notification_channels WHERE id = %s AND user_id = %s", (channel_id, user["id"])
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Channel not found")
    await conn.commit()
