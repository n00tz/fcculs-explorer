"""Unified free-text search across callsigns, ASR registration numbers, and
licensee/entity names -- the primary entry point for "find this callsign or
ULS ID" per the product requirements.
"""
from fastapi import APIRouter, Depends, Query
from psycopg import AsyncConnection

from ..db import get_db

router = APIRouter(prefix="/api/search", tags=["search"])

_SEARCH_SQL = """
(
    SELECT 'amateur' AS result_type, call_sign AS key, call_sign AS label,
           unique_system_identifier, similarity(call_sign, %(q)s) AS score
    FROM amat_hd
    WHERE call_sign %% %(q)s
    ORDER BY score DESC
    LIMIT %(limit)s
)
UNION ALL
(
    SELECT 'tower' AS result_type, registration_number AS key, registration_number AS label,
           unique_system_identifier, similarity(registration_number, %(q)s) AS score
    FROM tower_ra
    WHERE registration_number %% %(q)s
    ORDER BY score DESC
    LIMIT %(limit)s
)
UNION ALL
(
    SELECT 'amateur_entity' AS result_type, call_sign AS key, entity_name AS label,
           unique_system_identifier, similarity(entity_name, %(q)s) AS score
    FROM amat_en
    WHERE entity_name %% %(q)s
    ORDER BY score DESC
    LIMIT %(limit)s
)
UNION ALL
(
    SELECT 'tower_entity' AS result_type, registration_number AS key, entity_name AS label,
           unique_system_identifier, similarity(entity_name, %(q)s) AS score
    FROM tower_en
    WHERE entity_name %% %(q)s
    ORDER BY score DESC
    LIMIT %(limit)s
)
ORDER BY score DESC
LIMIT %(limit)s
"""


@router.get("")
async def search(
    q: str = Query(..., min_length=2, description="Callsign, ASR registration number, or name fragment"),
    limit: int = Query(20, ge=1, le=100),
    conn: AsyncConnection = Depends(get_db),
):
    """Trigram-similarity search. An exact-match callsign/registration number
    always scores 1.0 and sorts first; partial/fuzzy matches follow."""
    q_upper = q.strip().upper()
    async with conn.cursor() as cur:
        await cur.execute(_SEARCH_SQL, {"q": q_upper, "limit": limit})
        rows = await cur.fetchall()
    return {"query": q, "results": rows}
