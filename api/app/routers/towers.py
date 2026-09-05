"""Browse/detail endpoints for Antenna Structure Registration (Tower) data."""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from ..db import get_db
from ..pagination import Page, PageParams

router = APIRouter(prefix="/api/towers", tags=["towers"])


@router.get("", response_model=Page)
async def browse_towers(
    state: str | None = Query(None, min_length=2, max_length=2),
    status_code: str | None = Query(None, alias="status"),
    structure_type: str | None = Query(None, alias="structureType"),
    page_params: PageParams = Depends(),
    conn: AsyncConnection = Depends(get_db),
):
    conditions = []
    params: dict = {}
    if state:
        conditions.append("ra.structure_state_code = %(state)s")
        params["state"] = state.upper()
    if status_code:
        conditions.append("ra.status_code = %(status_code)s")
        params["status_code"] = status_code.upper()
    if structure_type:
        conditions.append("ra.structure_type = %(structure_type)s")
        params["structure_type"] = structure_type.upper()
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with conn.cursor() as cur:
        await cur.execute(f"SELECT count(*) AS total FROM tower_ra ra {where_clause}", params)
        total = (await cur.fetchone())["total"]

        await cur.execute(
            f"""
            SELECT ra.registration_number, ra.structure_type, ra.status_code,
                   ra.structure_city, ra.structure_state_code,
                   ra.overall_height_above_ground, ra.date_constructed
            FROM tower_ra ra
            {where_clause}
            ORDER BY ra.registration_number
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": page_params.limit, "offset": page_params.offset},
        )
        rows = await cur.fetchall()

    return Page(items=rows, page=page_params.page, page_size=page_params.page_size, total=total)


@router.get("/{registration_number}")
async def tower_detail(registration_number: str, conn: AsyncConnection = Depends(get_db)):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT * FROM tower_ra WHERE registration_number = %s", (registration_number,)
        )
        ra = await cur.fetchone()
        if ra is None:
            raise HTTPException(status_code=404, detail="Registration number not found")

        await cur.execute(
            "SELECT * FROM tower_en WHERE registration_number = %s", (registration_number,)
        )
        entities = await cur.fetchall()

        await cur.execute(
            "SELECT * FROM tower_co WHERE registration_number = %s ORDER BY coordinate_type, array_tower_position",
            (registration_number,),
        )
        coordinates = await cur.fetchall()

        await cur.execute(
            "SELECT * FROM tower_hs WHERE registration_number = %s ORDER BY date DESC NULLS LAST",
            (registration_number,),
        )
        history = await cur.fetchall()

        await cur.execute(
            """
            SELECT field_name, old_value, new_value, source_file, effective_date, detected_at
            FROM change_events
            WHERE subject_type = 'tower' AND subject_key = %s
            ORDER BY detected_at DESC
            LIMIT 100
            """,
            (registration_number,),
        )
        change_log = await cur.fetchall()

        related_by_site = []
        await cur.execute(
            "SELECT lat_site_key, lon_site_key FROM towers_by_site WHERE registration_number = %s",
            (registration_number,),
        )
        site_key = await cur.fetchone()
        if site_key:
            await cur.execute(
                """
                SELECT registration_number, structure_city, structure_state_code
                FROM towers_by_site
                WHERE lat_site_key = %s AND lon_site_key = %s AND registration_number <> %s
                """,
                (site_key["lat_site_key"], site_key["lon_site_key"], registration_number),
            )
            related_by_site = await cur.fetchall()

        related_by_frn = []
        frns = {e["frn"] for e in entities if e.get("frn")}
        if frns:
            await cur.execute(
                """
                SELECT source, subject_key, entity_name, licensee_id
                FROM identity_by_frn
                WHERE frn = ANY(%s) AND subject_key <> %s
                """,
                (list(frns), registration_number),
            )
            related_by_frn = await cur.fetchall()

    return {
        "registration": ra,
        "entities": entities,
        "coordinates": coordinates,
        "history": history,
        "change_log": change_log,
        "related_by_site": related_by_site,
        "related_by_frn": related_by_frn,
    }
