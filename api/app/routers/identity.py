"""Standalone identity-grouping lookups (FRN / mailing address), useful for
discovering "everything tied to this licensee" without starting from a
specific callsign or tower detail page.

These are the most expensive reads in the app -- both hit materialized
views that UNION all five ingested services -- so they carry the same
per-IP rate limit as search/browse rather than being left unthrottled.
"""
from fastapi import APIRouter, Depends, Request
from psycopg import AsyncConnection

from ..config import settings
from ..db import get_db
from ..ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.get("/frn/{frn}")
async def by_frn(
    request: Request,
    frn: str,
    conn: AsyncConnection = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"identity-frn:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )
    async with conn.cursor() as cur:
        await cur.execute("SELECT source, subject_key, entity_name, licensee_id FROM identity_by_frn WHERE frn = %s", (frn,))
        rows = await cur.fetchall()
    return {"frn": frn, "members": rows}


@router.get("/address")
async def by_address(
    request: Request,
    street_address: str,
    city: str,
    state: str,
    zip_code: str,
    conn: AsyncConnection = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"identity-address:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )
    address_key = f"{street_address.strip().lower()}|{city.strip().lower()}|{state.strip().upper()}|{zip_code[:5]}"
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT source, subject_key, entity_name FROM entities_by_address WHERE address_key = %s",
            (address_key,),
        )
        rows = await cur.fetchall()
    return {"address_key": address_key, "members": rows}
