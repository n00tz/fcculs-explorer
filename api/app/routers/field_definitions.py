"""Field help text and FCC code decodings, served to non-browser clients.

The web UI decodes raw FCC codes (`license_status = 'A'` -> "Active") from
`web/src/lib/fieldDefs.js`. Until now that table existed only in the
frontend bundle, so anything consuming the REST API directly -- including
the MCP server -- received undecodable raw codes where a human sees an
explanatory tooltip. This router closes that gap using the generated
server-side copy of the same table.

Read-only, unauthenticated, and rate-limited like the rest of the public
read surface.
"""
from fastapi import APIRouter, HTTPException, Query, Request

from ..config import settings
from ..field_defs import CODE_MAPS, FIELD_HELP, describe_code
from ..ratelimit import enforce_rate_limit

router = APIRouter(prefix="/api/field-definitions", tags=["field-definitions"])


@router.get("")
async def all_field_definitions(request: Request):
    """Every field-help string and code-decoding table in one response.

    Small enough (about 60 fields and 175 codes) to serve whole, which lets
    a client cache it once instead of making a lookup call per code.
    """
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"field-definitions:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )
    return {"field_help": FIELD_HELP, "code_maps": CODE_MAPS}


@router.get("/describe")
async def describe(
    request: Request,
    category: str = Query(..., description="Code category, e.g. 'license_status'."),
    code: str = Query(..., description="The raw FCC code to decode, e.g. 'A'."),
):
    """Decode a single code, for a client that would rather ask than cache.

    Returns `description: null` for an unmapped code rather than 404-ing:
    an unknown code is a normal outcome (FCC adds values, and several
    categories are deliberately left undecoded), and the documented
    behaviour everywhere else in this project is to fall back to showing
    the raw code unchanged.
    """
    client_ip = request.client.host if request.client else "unknown"
    await enforce_rate_limit(
        f"field-definitions:{client_ip}",
        settings.rate_limit_search_max,
        settings.rate_limit_search_window_seconds,
    )
    if category not in CODE_MAPS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category. Known categories: {sorted(CODE_MAPS)}",
        )
    return {
        "category": category,
        "code": code,
        "description": describe_code(category, code),
        "field_help": FIELD_HELP.get(category, ""),
    }
