"""Read-only access to the `change_events` diff log.

Detail pages already render a per-subject change log inline, but nothing
exposed the log as a standalone, queryable resource. This router does, so
an external client (notably the MCP server) can ask "what changed for this
callsign / FRN / registration number, and when" without scraping a detail
payload.

Read-only and unauthenticated, matching the rest of the browse/search
surface, and rate-limited on the same per-IP tier.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import AsyncConnection

from ..config import settings
from ..db import get_db
from ..pagination import Page, PageParams
from ..ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/history", tags=["history"])

# The `subject_type` values the ingestor actually writes (see
# ingestor/ingest.py's SUBJECT_TYPE map). Validated as an allow-list so an
# arbitrary string can never reach the query, and so a caller gets a clear
# 400 listing the real options instead of a silently empty result set.
ALLOWED_SUBJECT_TYPES = (
    "amateur_license",
    "tower",
    "gmrs_license",
    "aircraft_license",
    "ship_license",
)

# Service names as exposed everywhere else in the app -> the subject_type
# the ingestor stamps. Lets a caller pass the friendlier `service=amateur`
# instead of having to know the internal suffix convention.
SERVICE_TO_SUBJECT_TYPE = {
    "amateur": "amateur_license",
    "tower": "tower",
    "gmrs": "gmrs_license",
    "aircraft": "aircraft_license",
    "ship": "ship_license",
}


@router.get("", response_model=Page)
async def change_history(
    request: Request,
    subject_key: str | None = Query(
        None,
        description="Callsign or ASR registration number. Either this or frn is required.",
    ),
    frn: str | None = Query(
        None,
        description=(
            "FCC Registration Number. Returns events across every service tied "
            "to this FRN. Either this or subject_key is required."
        ),
    ),
    subject_type: str | None = Query(
        None, description=f"One of {list(ALLOWED_SUBJECT_TYPES)}."
    ),
    service: str | None = Query(
        None,
        description=(
            "Friendlier alias for subject_type: one of "
            f"{list(SERVICE_TO_SUBJECT_TYPE)}."
        ),
    ),
    since: date | None = Query(None, description="Only events on/after this date."),
    until: date | None = Query(None, description="Only events on/before this date."),
    page_params: PageParams = Depends(),
    conn: AsyncConnection = Depends(get_db),
):
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"history:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )

    if subject_key is None and frn is None:
        raise HTTPException(
            status_code=400, detail="Provide either subject_key or frn."
        )
    if subject_type is not None and service is not None:
        raise HTTPException(
            status_code=400, detail="Pass either subject_type or service, not both."
        )
    if service is not None:
        resolved = SERVICE_TO_SUBJECT_TYPE.get(service.strip().lower())
        if resolved is None:
            raise HTTPException(
                status_code=400,
                detail=f"service must be one of {sorted(SERVICE_TO_SUBJECT_TYPE)}",
            )
        subject_type = resolved
    elif subject_type is not None:
        subject_type = subject_type.strip().lower()
        if subject_type not in ALLOWED_SUBJECT_TYPES:
            raise HTTPException(
                status_code=400,
                detail=f"subject_type must be one of {sorted(ALLOWED_SUBJECT_TYPES)}",
            )

    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=400, detail="since must be on or before until.")

    conditions = []
    params: dict = {}
    # Subject keys are stored upper-cased (callsigns and ASR registration
    # numbers both are), so normalize rather than making the caller guess.
    if subject_key is not None:
        conditions.append("subject_key = %(subject_key)s")
        params["subject_key"] = subject_key.strip().upper()
    if frn is not None:
        conditions.append("frn = %(frn)s")
        params["frn"] = frn.strip()
    # Note: filtering is deliberately by subject_type rather than the
    # change_events.service column. `service` was only added in migration
    # 008 and is NULL for every event recorded before it, whereas
    # subject_type has been stamped since the very first ingest -- so
    # filtering on it is the only way to get correct historical results.
    if subject_type is not None:
        conditions.append("subject_type = %(subject_type)s")
        params["subject_type"] = subject_type
    if since is not None:
        conditions.append("effective_date >= %(since)s")
        params["since"] = since
    if until is not None:
        conditions.append("effective_date <= %(until)s")
        params["until"] = until
    where = " AND ".join(conditions)

    async with conn.cursor() as cur:
        await cur.execute(f"SELECT COUNT(*) AS n FROM change_events WHERE {where}", params)
        total_row = await cur.fetchone()
        total = total_row["n"] if total_row else 0

        await cur.execute(
            f"""
            SELECT subject_type, subject_key, uls_system_id, frn, service,
                   field_name, old_value, new_value, source_file,
                   effective_date, detected_at, is_new_operator
            FROM change_events
            WHERE {where}
            ORDER BY effective_date DESC, detected_at DESC, id DESC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {**params, "limit": page_params.limit, "offset": page_params.offset},
        )
        rows = await cur.fetchall()

    return Page(
        items=rows,
        page=page_params.page,
        page_size=page_params.page_size,
        total=total,
    )
