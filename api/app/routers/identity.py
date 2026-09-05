"""Standalone identity-grouping lookups (FRN / mailing address), useful for
discovering "everything tied to this licensee" without starting from a
specific callsign or tower detail page."""
from fastapi import APIRouter, Depends
from psycopg import AsyncConnection

from ..db import get_db

router = APIRouter(prefix="/api/identity", tags=["identity"])


@router.get("/frn/{frn}")
async def by_frn(frn: str, conn: AsyncConnection = Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute("SELECT source, subject_key, entity_name, licensee_id FROM identity_by_frn WHERE frn = %s", (frn,))
        rows = await cur.fetchall()
    return {"frn": frn, "members": rows}


@router.get("/address")
async def by_address(
    street_address: str, city: str, state: str, zip_code: str, conn: AsyncConnection = Depends(get_db)
):
    address_key = f"{street_address.strip().lower()}|{city.strip().lower()}|{state.strip().upper()}|{zip_code[:5]}"
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT source, subject_key, entity_name FROM entities_by_address WHERE address_key = %s",
            (address_key,),
        )
        rows = await cur.fetchall()
    return {"address_key": address_key, "members": rows}
