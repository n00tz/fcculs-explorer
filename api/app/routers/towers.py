"""Browse/detail endpoints for Antenna Structure Registration (Tower) data."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import AsyncConnection

from ..config import settings
from ..db import get_db
from ..pagination import Page, PageParams, resolve_sort
from ..ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/towers", tags=["towers"])

# Allow-list mapping the columns actually displayed in the Tower browse
# table to their real SQL expressions -- see amateur.py's SORTABLE_COLUMNS
# for the same rationale (validated against this, never interpolated raw).
SORTABLE_COLUMNS = {
    "registration_number": "ra.registration_number",
    "structure_type": "ra.structure_type",
    "status_code": "ra.status_code",
    "city": "ra.structure_city",
    "state": "ra.structure_state_code",
    "overall_height_above_ground": "ra.overall_height_above_ground",
    "date_constructed": "ra.date_constructed",
}


@router.get("", response_model=Page)
async def browse_towers(
    request: Request,
    registration_number: str | None = Query(None, alias="registrationNumber"),
    structure_type: str | None = Query(None, alias="structureType"),
    city: str | None = Query(None),
    state: str | None = Query(None),
    status_code: str | None = Query(None, alias="status"),
    height_min: float | None = Query(None, alias="heightMin"),
    height_max: float | None = Query(None, alias="heightMax"),
    constructed_after: str | None = Query(None, alias="constructedAfter"),
    constructed_before: str | None = Query(None, alias="constructedBefore"),
    sort: str | None = Query(None, description=f"One of {sorted(SORTABLE_COLUMNS)}"),
    order: str | None = Query(None, description="asc or desc"),
    page_params: PageParams = Depends(),
    conn: AsyncConnection = Depends(get_db),
):
    sort_expr, sort_direction = resolve_sort(sort, order, SORTABLE_COLUMNS, default_column="registration_number")
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"towers-browse:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )
    conditions = []
    params: dict = {}
    # Partial (ILIKE) matching on every text field shown in the browse
    # table, plus numeric/date range filters for height and construction
    # date -- all displayed columns are filterable.
    if registration_number:
        conditions.append("ra.registration_number ILIKE %(registration_number)s")
        params["registration_number"] = f"%{registration_number.strip()}%"
    if structure_type:
        conditions.append("ra.structure_type ILIKE %(structure_type)s")
        params["structure_type"] = f"%{structure_type.strip()}%"
    if city:
        conditions.append("ra.structure_city ILIKE %(city)s")
        params["city"] = f"%{city.strip()}%"
    if state:
        conditions.append("ra.structure_state_code ILIKE %(state)s")
        params["state"] = f"%{state.strip()}%"
    if status_code:
        conditions.append("ra.status_code = %(status_code)s")
        params["status_code"] = status_code.upper()
    if height_min is not None:
        conditions.append("ra.overall_height_above_ground >= %(height_min)s")
        params["height_min"] = height_min
    if height_max is not None:
        conditions.append("ra.overall_height_above_ground <= %(height_max)s")
        params["height_max"] = height_max
    if constructed_after:
        conditions.append("ra.date_constructed >= %(constructed_after)s")
        params["constructed_after"] = constructed_after
    if constructed_before:
        conditions.append("ra.date_constructed <= %(constructed_before)s")
        params["constructed_before"] = constructed_before
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
            ORDER BY {sort_expr} {sort_direction} NULLS LAST, ra.registration_number
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
