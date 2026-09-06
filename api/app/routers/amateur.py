"""Browse/detail endpoints for Amateur Radio Service licenses."""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from ..db import get_db
from ..history_codes import describe_history_code
from ..pagination import Page, PageParams, resolve_sort

router = APIRouter(prefix="/api/amateur", tags=["amateur"])

# Allow-list mapping the columns actually displayed in the Amateur browse
# table to their real SQL expressions -- sort/order query params are
# validated against this (never interpolated raw) to prevent SQL injection
# via arbitrary column names.
SORTABLE_COLUMNS = {
    "call_sign": "hd.call_sign",
    "license_status": "hd.license_status",
    "operator_class": "am.operator_class",
    "entity_name": "en.entity_name",
    "state": "en.state",
    "city": "en.city",
    "grant_date": "hd.grant_date",
    "expired_date": "hd.expired_date",
}


@router.get("", response_model=Page)
async def browse_amateur(
    callsign: str | None = Query(None),
    name: str | None = Query(None),
    city: str | None = Query(None),
    state: str | None = Query(None),
    status_code: str | None = Query(None, alias="status"),
    operator_class: str | None = Query(None, alias="class"),
    sort: str | None = Query(None, description=f"One of {sorted(SORTABLE_COLUMNS)}"),
    order: str | None = Query(None, description="asc or desc"),
    page_params: PageParams = Depends(),
    conn: AsyncConnection = Depends(get_db),
):
    sort_expr, sort_direction = resolve_sort(sort, order, SORTABLE_COLUMNS, default_column="call_sign")
    conditions = []
    params: dict = {}
    # Partial (ILIKE) matching on the human-facing fields so "ring", "GA",
    # "N0O" etc. all work, per the browse/filter requirement.
    if callsign:
        conditions.append("hd.call_sign ILIKE %(callsign)s")
        params["callsign"] = f"%{callsign.strip()}%"
    if name:
        conditions.append(
            "(en.entity_name ILIKE %(name)s OR en.first_name ILIKE %(name)s OR en.last_name ILIKE %(name)s)"
        )
        params["name"] = f"%{name.strip()}%"
    if city:
        conditions.append("en.city ILIKE %(city)s")
        params["city"] = f"%{city.strip()}%"
    if state:
        conditions.append("en.state ILIKE %(state)s")
        params["state"] = f"%{state.strip()}%"
    if status_code:
        conditions.append("hd.license_status = %(status_code)s")
        params["status_code"] = status_code.upper()
    if operator_class:
        conditions.append("am.operator_class = %(operator_class)s")
        params["operator_class"] = operator_class.upper()
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT count(*) AS total
            FROM amat_hd hd
            LEFT JOIN amat_en en ON en.unique_system_identifier = hd.unique_system_identifier
            LEFT JOIN amat_am am ON am.unique_system_identifier = hd.unique_system_identifier
            {where_clause}
            """,
            params,
        )
        total = (await cur.fetchone())["total"]

        await cur.execute(
            f"""
            SELECT hd.call_sign, hd.license_status, hd.grant_date, hd.expired_date,
                   am.operator_class, am.group_code, en.entity_name, en.state, en.city
            FROM amat_hd hd
            LEFT JOIN amat_en en ON en.unique_system_identifier = hd.unique_system_identifier
            LEFT JOIN amat_am am ON am.unique_system_identifier = hd.unique_system_identifier
            {where_clause}
            ORDER BY {sort_expr} {sort_direction} NULLS LAST, hd.call_sign
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": page_params.limit, "offset": page_params.offset},
        )
        rows = await cur.fetchall()

    return Page(items=rows, page=page_params.page, page_size=page_params.page_size, total=total)


@router.get("/{call_sign}")
async def amateur_detail(call_sign: str, conn: AsyncConnection = Depends(get_db)):
    call_sign = call_sign.upper()
    async with conn.cursor() as cur:
        # A callsign can have MULTIPLE unique_system_identifier rows across
        # time (reassigned as a vanity after a prior holder's license
        # expired). Resolve the CURRENT holder: prefer the active ('A')
        # record, otherwise the most recently granted. All other sections
        # scope to that same USID so we never blend two holders' data.
        await cur.execute(
            """
            SELECT unique_system_identifier FROM amat_hd
            WHERE call_sign = %s
            ORDER BY (license_status = 'A') DESC, grant_date DESC NULLS LAST
            LIMIT 1
            """,
            (call_sign,),
        )
        row = await cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Callsign not found")
        usid = row["unique_system_identifier"]

        await cur.execute("SELECT * FROM amat_hd WHERE unique_system_identifier = %s", (usid,))
        hd = await cur.fetchone()

        await cur.execute("SELECT * FROM amat_en WHERE unique_system_identifier = %s", (usid,))
        entity = await cur.fetchone()

        await cur.execute("SELECT * FROM amat_am WHERE unique_system_identifier = %s", (usid,))
        amateur_specific = await cur.fetchone()

        # Full callsign history across ALL holders (every USID), so the
        # timeline shows e.g. a prior holder's expiry then the vanity grant.
        await cur.execute(
            "SELECT * FROM amat_hs WHERE callsign = %s ORDER BY log_date DESC NULLS LAST",
            (call_sign,),
        )
        history = await cur.fetchall()
        for h in history:
            h["code_description"] = describe_history_code(h.get("code"))

        await cur.execute(
            """
            SELECT field_name, old_value, new_value, source_file, effective_date, detected_at
            FROM change_events
            WHERE subject_type = 'amateur_license' AND subject_key = %s
            ORDER BY detected_at DESC
            LIMIT 100
            """,
            (call_sign,),
        )
        change_log = await cur.fetchall()

        related = []
        if entity and entity.get("frn"):
            await cur.execute(
                """
                SELECT source, subject_key, entity_name, licensee_id
                FROM identity_by_frn
                WHERE frn = %s AND subject_key <> %s
                """,
                (entity["frn"], call_sign),
            )
            related = await cur.fetchall()

    return {
        "header": hd,
        "entity": entity,
        "amateur_specific": amateur_specific,
        "history": history,
        "change_log": change_log,
        "related_identities": related,
    }
