"""Passwordless magic-link authentication.

Flow:
1. POST /auth/request-link {email} -- always returns a generic 202, whether
   or not the email exists, to avoid leaking account existence. Creates (or
   reuses) a user row, issues a single-use token, emails a signed link.
2. GET /auth/verify?token=... -- looks up the token by hash, checks
   expiry/consumption, marks it consumed, and sets a signed session cookie.
3. POST /auth/logout -- clears the session cookie.
4. GET /auth/me -- returns the current user, or 401.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from psycopg import AsyncConnection
from pydantic import BaseModel, EmailStr

from ..config import settings
from ..db import get_db
from ..deps import get_current_user
from ..mailer import send_magic_link_email
from ..security import create_session_cookie, generate_magic_link_token, hash_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RequestLinkBody(BaseModel):
    email: EmailStr


@router.post("/request-link", status_code=status.HTTP_202_ACCEPTED)
async def request_link(body: RequestLinkBody, conn: AsyncConnection = Depends(get_db)):
    email = body.email.lower()
    async with conn.cursor() as cur:
        await cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        user = await cur.fetchone()
        if user is None:
            await cur.execute(
                "INSERT INTO users (email) VALUES (%s) RETURNING id", (email,)
            )
            user = await cur.fetchone()
        user_id = user["id"]

        raw_token, token_hash, expires_at = generate_magic_link_token()
        await cur.execute(
            "INSERT INTO magic_link_tokens (user_id, token_hash, expires_at) VALUES (%s, %s, %s)",
            (user_id, token_hash, expires_at),
        )
    await conn.commit()

    link_url = f"{settings.magic_link_base_url}/auth/callback?token={raw_token}"
    await send_magic_link_email(email, link_url)

    return {"detail": "If that email is valid, a sign-in link has been sent."}


@router.get("/verify")
async def verify(token: str, response: Response, conn: AsyncConnection = Depends(get_db)):
    token_hash = hash_token(token)
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT id, user_id, expires_at, consumed_at FROM magic_link_tokens WHERE token_hash = %s",
            (token_hash,),
        )
        record = await cur.fetchone()
        if record is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid token")
        if record["consumed_at"] is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token already used")
        if record["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token expired")

        await cur.execute(
            "UPDATE magic_link_tokens SET consumed_at = now() WHERE id = %s", (record["id"],)
        )
    await conn.commit()

    cookie_value = create_session_cookie(record["user_id"])
    response.set_cookie(
        settings.session_cookie_name,
        cookie_value,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.magic_link_base_url.startswith("https://"),
    )
    return {"detail": "Signed in"}


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(settings.session_cookie_name)
    return {"detail": "Signed out"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"id": user["id"], "email": user["email"]}
