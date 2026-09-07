"""Unified free-text search across callsigns, ASR registration numbers, and
licensee/entity names -- the primary entry point for "find this callsign or
ULS ID" per the product requirements.
"""
from fastapi import APIRouter, Depends, Query, Request
from psycopg import AsyncConnection

from ..config import settings
from ..db import get_db
from ..ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/search", tags=["search"])


def _arm(result_type: str, table: str, key_column: str, label_column: str) -> str:
    """One trigram-matched UNION arm of the search query.

    Every column referenced here is a hardcoded identifier from the table
    definitions below -- never user input -- so this stays injection-safe;
    only %(q)s / %(limit)s are parameterized values.

    Each arm matches against a pg_trgm GIN index, so adding services costs
    an index lookup per arm rather than a scan.
    """
    return f"""
(
    SELECT '{result_type}' AS result_type, {key_column} AS key, {label_column} AS label,
           unique_system_identifier, similarity({label_column}, %(q)s) AS score
    FROM {table}
    WHERE {label_column} %% %(q)s
    ORDER BY score DESC
    LIMIT %(limit)s
)"""


# (result_type, table, key column, searched/label column)
_SEARCH_ARMS = [
    # Callsign / registration-number identifiers.
    ("amateur", "amat_hd", "call_sign", "call_sign"),
    ("tower", "tower_ra", "registration_number", "registration_number"),
    ("gmrs", "gmrs_hd", "call_sign", "call_sign"),
    ("aircraft", "aircr_hd", "call_sign", "call_sign"),
    ("ship", "ship_hd", "call_sign", "call_sign"),
    # Licensee / entity names.
    ("amateur_entity", "amat_en", "call_sign", "entity_name"),
    ("tower_entity", "tower_en", "registration_number", "entity_name"),
    ("gmrs_entity", "gmrs_en", "call_sign", "entity_name"),
    ("aircraft_entity", "aircr_en", "call_sign", "entity_name"),
    ("ship_entity", "ship_en", "call_sign", "entity_name"),
    # Service-specific real-world identifiers people actually search by:
    # an aircraft's FAA tail number and a vessel's name.
    ("aircraft_n_number", "aircr_ac", "call_sign", "n_number"),
    ("ship_name", "ship_sh", "callsign", "ship_name"),
]

_SEARCH_SQL = "\nUNION ALL\n".join(_arm(*arm) for arm in _SEARCH_ARMS) + """
ORDER BY score DESC
LIMIT %(limit)s
"""


@router.get("")
async def search(
    request: Request,
    q: str = Query(..., min_length=2, description="Callsign, ASR registration number, or name fragment"),
    limit: int = Query(20, ge=1, le=100),
    conn: AsyncConnection = Depends(get_db),
):
    """Trigram-similarity search. An exact-match callsign/registration number
    always scores 1.0 and sorts first; partial/fuzzy matches follow."""
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"search:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )
    q_upper = q.strip().upper()
    async with conn.cursor() as cur:
        await cur.execute(_SEARCH_SQL, {"q": q_upper, "limit": limit})
        rows = await cur.fetchall()
    return {"query": q, "results": rows}
