"""Browse/detail endpoints for Amateur Radio Service licenses."""
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import AsyncConnection

from ..db import get_db
from ..pagination import Page, PageParams

router = APIRouter(prefix="/api/amateur", tags=["amateur"])


@router.get("", response_model=Page)
async def browse_amateur(
    state: str | None = Query(None, min_length=2, max_length=2),
    status_code: str | None = Query(None, alias="status"),
    operator_class: str | None = Query(None, alias="class"),
    page_params: PageParams = Depends(),
    conn: AsyncConnection = Depends(get_db),
):
    conditions = []
    params: dict = {}
    if state:
        conditions.append("en.state = %(state)s")
        params["state"] = state.upper()
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
            ORDER BY hd.call_sign
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
        await cur.execute("SELECT * FROM amat_hd WHERE call_sign = %s", (call_sign,))
        hd = await cur.fetchone()
        if hd is None:
            raise HTTPException(status_code=404, detail="Callsign not found")

        await cur.execute("SELECT * FROM amat_en WHERE call_sign = %s", (call_sign,))
        entity = await cur.fetchone()

        await cur.execute("SELECT * FROM amat_am WHERE callsign = %s", (call_sign,))
        amateur_specific = await cur.fetchone()

        await cur.execute(
            "SELECT * FROM amat_hs WHERE callsign = %s ORDER BY log_date DESC NULLS LAST",
            (call_sign,),
        )
        history = await cur.fetchall()

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
