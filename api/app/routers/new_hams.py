"""Public read endpoint celebrating brand-new amateur radio grants: people
(and clubs) who have never held a callsign before, per change_events'
durable is_new_operator flag (see db/006_new_operator_celebration.sql and
ingestor/db.py's frn_has_prior_amateur_license()).

Scoped to a rolling NEW_HAMS_WINDOW_DAYS window (on the ingest effective
date, so ingestion gaps are visible) and ordered by grant date then
callsign -- grant date is the column the UI actually displays, so a
missing day of FCC ingestion shows up as a visible gap in
the dates rather than being hidden by more recent grants backfilling the
page (see docs/plan.md's daily-ingest catch-up redesign)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import AsyncConnection
from pydantic import BaseModel

from ..config import settings
from ..db import get_db
from ..ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/new-hams", tags=["new-hams"])

# How far back the celebration looks. Deliberately a little longer than a
# week so that a gap in daily ingestion (FCC only keeps a rolling 7 weekday
# files, so a missed day is unrecoverable once rotated) is visible at a
# glance as a missing date in the listing, rather than silently scrolling
# away behind whatever the most recent N grants happen to be.
NEW_HAMS_WINDOW_DAYS = 10

# Validated against an allow-list (never interpolated raw) -- same
# SQL-injection-safety pattern used for sort/order elsewhere in this project.
TYPE_FILTERS = {
    "individual": "en.applicant_type_code = 'I'",
    "club": "en.applicant_type_code = 'B'",
}


class NewHamsPage(BaseModel):
    items: list
    page: int
    page_size: int
    total: int
    total_individuals: int
    total_clubs: int
    window_days: int = NEW_HAMS_WINDOW_DAYS


@router.get("", response_model=NewHamsPage)
async def new_hams(
    request: Request,
    type: str | None = Query(None, description="Optional: 'individual' or 'club'"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    conn: AsyncConnection = Depends(get_db),
):
    if type is not None and type not in TYPE_FILTERS:
        raise HTTPException(status_code=400, detail="type must be 'individual' or 'club'")

    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"new-hams:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )

    type_condition = f"AND {TYPE_FILTERS[type]}" if type else ""
    offset = (page - 1) * page_size

    async with conn.cursor() as cur:
        # Split counts (individual vs club) computed in one pass via
        # FILTER, independent of the optional `type` narrow, so the
        # homepage summary line always shows both totals regardless of
        # which subset the caller is currently paging through.
        await cur.execute(
            f"""
            SELECT
                count(*) FILTER (WHERE en.applicant_type_code = 'I') AS total_individuals,
                count(*) FILTER (WHERE en.applicant_type_code = 'B') AS total_clubs
            FROM change_events ce
            JOIN amat_en en ON en.unique_system_identifier = ce.uls_system_id::bigint
            WHERE ce.is_new_operator
              AND ce.effective_date >= current_date - %(window_days)s::int
              AND en.applicant_type_code IN ('I', 'B')
            """,
            {"window_days": NEW_HAMS_WINDOW_DAYS},
        )
        counts = await cur.fetchone()
        total_individuals = counts["total_individuals"]
        total_clubs = counts["total_clubs"]
        total = total_individuals + total_clubs if not type else (
            total_individuals if type == "individual" else total_clubs
        )

        await cur.execute(
            f"""
            SELECT
                hd.call_sign,
                en.entity_name AS name,
                en.city,
                en.state,
                hd.grant_date,
                am.operator_class,
                CASE en.applicant_type_code WHEN 'I' THEN 'individual' ELSE 'club' END AS applicant_type
            FROM change_events ce
            JOIN amat_en en ON en.unique_system_identifier = ce.uls_system_id::bigint
            LEFT JOIN amat_hd hd ON hd.unique_system_identifier = en.unique_system_identifier
            LEFT JOIN amat_am am ON am.unique_system_identifier = en.unique_system_identifier
            WHERE ce.is_new_operator
              AND ce.effective_date >= current_date - %(window_days)s::int
              AND en.applicant_type_code IN ('I', 'B')
              {type_condition}
            ORDER BY hd.grant_date DESC NULLS LAST, hd.call_sign ASC
            LIMIT %(limit)s OFFSET %(offset)s
            """,
            {"limit": page_size, "offset": offset, "window_days": NEW_HAMS_WINDOW_DAYS},
        )
        items = await cur.fetchall()

    return NewHamsPage(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
        total_individuals=total_individuals,
        total_clubs=total_clubs,
    )
