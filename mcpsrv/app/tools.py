"""MCP tool definitions for FCC ULS Explorer.

Every tool is a read-only passthrough to the REST API. Docstrings and type
annotations here are not decoration: the MCP SDK derives each tool's
description and JSON input schema directly from them, so they are the
entire interface an LLM client sees when deciding which tool to call and
how. They are written for that audience.

Page-size ceilings are enforced per-tool with Field(le=...) constraints.
The MCP protocol has no cap on tool result size, so bounding results is
this server's own responsibility -- an unbounded browse would blow out a
client's context window.
"""
from typing import Annotated, Any, Literal

from pydantic import Field

from .client import ApiError, client
from .config import settings

# Mirrors api/app/routers/personal_services.py's SERVICE_CONFIGS plus the
# two original services. Keyed by the name exposed to MCP clients.
SERVICE_PATHS: dict[str, str] = {
    "amateur": "/api/amateur",
    "gmrs": "/api/gmrs",
    "aircraft": "/api/aircraft",
    "ship": "/api/ship",
}

LicenseService = Literal["amateur", "gmrs", "aircraft", "ship"]

PageSize = Annotated[
    int,
    Field(
        ge=1,
        le=settings.max_page_size,
        description="Results per page. Keep small; large pages waste context.",
    ),
]
PageNumber = Annotated[int, Field(ge=1, description="1-based page number.")]


def register_tools(mcp: Any) -> None:
    """Attach every tool to the given MCPServer instance."""

    # --- search ------------------------------------------------------

    @mcp.tool()
    async def search_uls(
        query: Annotated[
            str,
            Field(
                min_length=2,
                description=(
                    "A callsign, ASR tower registration number, or part of a "
                    "licensee/entity name."
                ),
            ),
        ],
        limit: Annotated[int, Field(ge=1, le=50)] = settings.default_page_size,
    ) -> dict:
        """Search across ALL FCC license data at once by callsign, tower
        registration number, or licensee name.

        This is the right starting point when you do not already know which
        radio service a callsign belongs to. It covers Amateur, GMRS,
        Aircraft and Ship licences plus Antenna Structure Registration
        (tower) records, and returns fuzzy matches ranked by similarity, so
        partial or slightly misspelled input still works. Each result
        includes a `result_type` telling you which service it came from and
        therefore which detail tool to call next.
        """
        return await _get("/api/search", {"q": query, "limit": limit})

    # --- browse ------------------------------------------------------

    @mcp.tool()
    async def browse_licenses(
        service: Annotated[
            LicenseService,
            Field(description="Which radio service's licences to list."),
        ],
        callsign: Annotated[str | None, Field(description="Partial callsign match.")] = None,
        name: Annotated[str | None, Field(description="Partial licensee name match.")] = None,
        city: str | None = None,
        state: Annotated[str | None, Field(description="Two-letter state code, e.g. GA.")] = None,
        status: Annotated[
            str | None,
            Field(description="License status code, e.g. A for Active, E for Expired."),
        ] = None,
        operator_class: Annotated[
            str | None,
            Field(
                description=(
                    "Amateur only: operator class code (T, G, E, A, N). "
                    "Ignored for other services."
                )
            ),
        ] = None,
        n_number: Annotated[
            str | None,
            Field(description="Aircraft only: FAA tail number, e.g. N123AB."),
        ] = None,
        ship_name: Annotated[str | None, Field(description="Ship only: vessel name.")] = None,
        mmsi: Annotated[str | None, Field(description="Ship only: MMSI station number.")] = None,
        sort: Annotated[
            str | None,
            Field(
                description=(
                    "Column to sort by, e.g. call_sign, entity_name, state, "
                    "grant_date, expired_date. Service-specific columns are "
                    "also allowed (n_number, ship_name)."
                )
            ),
        ] = None,
        order: Literal["asc", "desc"] | None = None,
        page: PageNumber = 1,
        page_size: PageSize = settings.default_page_size,
    ) -> dict:
        """List licences for one radio service, with optional filters.

        Use this to answer questions about groups of licensees ("active
        amateur licences in Georgia", "ship stations named ...") rather than
        one specific callsign. All text filters are partial matches, so
        fragments work. Results are paginated; check `total` in the response
        to see how many records matched overall.

        Some filters only apply to certain services: `operator_class` is
        Amateur only, `n_number` is Aircraft only, and `ship_name`/`mmsi`
        are Ship only.
        """
        path = _service_path(service)
        params: dict[str, Any] = {
            "callsign": callsign,
            "name": name,
            "city": city,
            "state": state,
            "status": status,
            "sort": sort,
            "order": order,
            "page": page,
            "page_size": page_size,
        }
        # Only forward service-specific filters to the service that accepts
        # them; the API rejects unknown query params for the others.
        if service == "amateur":
            params["class"] = operator_class
        if service == "aircraft":
            params["n_number"] = n_number
        if service == "ship":
            params["ship_name"] = ship_name
            params["mmsi"] = mmsi
        return await _get(path, params)

    @mcp.tool()
    async def browse_towers(
        registration_number: str | None = None,
        structure_type: Annotated[
            str | None,
            Field(description="Structure type code, e.g. LTOWER, GTOWER, MTOWER."),
        ] = None,
        city: str | None = None,
        state: Annotated[str | None, Field(description="Two-letter state code.")] = None,
        status: str | None = None,
        height_min: Annotated[
            float | None, Field(description="Minimum overall structure height in meters.")
        ] = None,
        height_max: Annotated[
            float | None, Field(description="Maximum overall structure height in meters.")
        ] = None,
        constructed_after: Annotated[
            str | None, Field(description="ISO date (YYYY-MM-DD).")
        ] = None,
        constructed_before: Annotated[
            str | None, Field(description="ISO date (YYYY-MM-DD).")
        ] = None,
        sort: str | None = None,
        order: Literal["asc", "desc"] | None = None,
        page: PageNumber = 1,
        page_size: PageSize = settings.default_page_size,
    ) -> dict:
        """List registered antenna structures (towers) from the FCC ASR
        database, with optional filters.

        Towers are a separate dataset from licences: they describe physical
        structures and their owners, and can be filtered by location, height
        and construction date.
        """
        params = {
            "registrationNumber": registration_number,
            "structureType": structure_type,
            "city": city,
            "state": state,
            "status": status,
            "heightMin": height_min,
            "heightMax": height_max,
            "constructedAfter": constructed_after,
            "constructedBefore": constructed_before,
            "sort": sort,
            "order": order,
            "page": page,
            "page_size": page_size,
        }
        return await _get("/api/towers", params)

    # --- detail ------------------------------------------------------

    @mcp.tool()
    async def get_license(
        service: Annotated[
            LicenseService, Field(description="Which radio service the callsign belongs to.")
        ],
        call_sign: Annotated[str, Field(description="The full callsign, e.g. N0OTZ.")],
    ) -> dict:
        """Get the complete record for one licence by callsign.

        Returns every stored attribute: licence header (status, grant and
        expiration dates), the licensee's name and address, any
        service-specific details (operator class for Amateur, tail number
        for Aircraft, vessel details and voyages for Ship), the licence
        application history, a log of recorded changes, and related records
        that share the same FRN or address.

        If you are not sure which service a callsign belongs to, call
        search_uls first.
        """
        path = f"{_service_path(service)}/{call_sign.strip().upper()}"
        return await _get(path)

    @mcp.tool()
    async def get_tower(
        registration_number: Annotated[
            str, Field(description="The ASR registration number, e.g. 1234567.")
        ],
    ) -> dict:
        """Get the complete record for one registered antenna structure.

        Includes the structure's coordinates, height, type, status, owner
        details, filing history, and other towers registered at the same
        site.
        """
        return await _get(f"/api/towers/{registration_number.strip()}")

    # --- identity grouping -------------------------------------------

    @mcp.tool()
    async def get_identity_by_frn(
        frn: Annotated[
            str,
            Field(description="The 10-digit FCC Registration Number, e.g. 0001112223."),
        ],
    ) -> dict:
        """Find every FCC record held under one FRN, across all services.

        An FRN (FCC Registration Number) identifies a person or
        organization, and one FRN commonly holds several licences -- an
        amateur callsign and a GMRS licence, for example, or many towers.
        This is the best way to see a licensee's complete FCC footprint in
        one call.
        """
        return await _get(f"/api/identity/frn/{frn.strip()}")

    @mcp.tool()
    async def get_identity_by_address(
        street_address: str,
        city: str,
        state: Annotated[str, Field(description="Two-letter state code.")],
        zip_code: str,
    ) -> dict:
        """Find every licensee registered at one mailing address.

        Useful for spotting clubs, families or organizations that share an
        address but use different FRNs. All four parts of the address are
        required, and they must match the stored values.
        """
        return await _get(
            "/api/identity/address",
            {
                "street_address": street_address,
                "city": city,
                "state": state,
                "zip_code": zip_code,
            },
        )

    # --- change history ----------------------------------------------

    @mcp.tool()
    async def get_change_history(
        subject_key: Annotated[
            str | None,
            Field(description="A callsign or ASR registration number to look up."),
        ] = None,
        frn: Annotated[
            str | None,
            Field(description="An FRN, to see changes across all of its records."),
        ] = None,
        service: Annotated[
            Literal["amateur", "tower", "gmrs", "aircraft", "ship"] | None,
            Field(description="Restrict to one service."),
        ] = None,
        since: Annotated[str | None, Field(description="ISO date (YYYY-MM-DD).")] = None,
        until: Annotated[str | None, Field(description="ISO date (YYYY-MM-DD).")] = None,
        page: PageNumber = 1,
        page_size: PageSize = settings.default_page_size,
    ) -> dict:
        """See what actually changed on a licence or tower over time.

        This service ingests the FCC's daily transaction files and records
        every field that changed, so this tool can answer questions like
        "when was this callsign granted?", "has this licence been renewed?"
        or "what changed recently for this FRN?".

        Supply either `subject_key` (a callsign or registration number) or
        `frn`; at least one is required. Results are newest first.
        """
        if not subject_key and not frn:
            return _error("Provide either subject_key or frn.")
        return await _get(
            "/api/history",
            {
                "subject_key": subject_key,
                "frn": frn,
                "service": service,
                "since": since,
                "until": until,
                "page": page,
                "page_size": page_size,
            },
        )

    # --- new hams ----------------------------------------------------

    @mcp.tool()
    async def get_new_hams(
        type: Annotated[
            Literal["individual", "club"] | None,
            Field(description="Restrict to individual operators or club stations."),
        ] = None,
        page: PageNumber = 1,
        page_size: PageSize = settings.default_page_size,
    ) -> dict:
        """List people who just earned their very first amateur radio
        callsign, plus newly licensed club stations.

        These are first-time licensees only -- someone receiving an
        additional callsign when they already held one is deliberately
        excluded. Each entry includes the callsign, name, city/state, grant
        date and operator class. The response also carries separate totals
        for individuals and clubs.

        This covers Amateur radio only; the FCC's other services do not have
        an equivalent first-licence concept.
        """
        return await _get(
            "/api/new-hams", {"type": type, "page": page, "page_size": page_size}
        )

    # --- code decoding -----------------------------------------------

    @mcp.tool()
    async def describe_code(
        category: Annotated[
            str,
            Field(
                description=(
                    "The field the code came from, e.g. license_status, "
                    "operator_class, applicant_type_code, structure_type."
                )
            ),
        ],
        code: Annotated[str, Field(description="The raw code value, e.g. A, E, LTOWER.")],
    ) -> dict:
        """Translate a raw FCC code into plain English.

        FCC data is full of single-letter and short codes (`A` for licence
        status, `E` for operator class, `LTOWER` for structure type). Use
        this to explain a value returned by any other tool rather than
        guessing at its meaning, since the same letter means different
        things in different fields.

        A `description` of null means that code is not in the FCC's
        published list for that field; report the raw code as-is rather
        than inventing a meaning for it.
        """
        return await _get(
            "/api/field-definitions/describe",
            {"category": category, "code": code},
        )

    @mcp.tool()
    async def list_field_definitions() -> dict:
        """Get the full reference of FCC field explanations and code
        meanings used across this dataset.

        Returns `field_help` (what each field means in plain language) and
        `code_maps` (every known code value and its meaning, grouped by
        field). Call this once if you need to interpret many fields; use
        describe_code for a single lookup.
        """
        return await _get("/api/field-definitions")


def _service_path(service: str) -> str:
    try:
        return SERVICE_PATHS[service]
    except KeyError:  # pragma: no cover - Literal typing prevents this
        raise ValueError(
            f"Unknown service {service!r}; expected one of {sorted(SERVICE_PATHS)}"
        )


async def _get(path: str, params: dict[str, Any] | None = None) -> dict:
    """GET from the REST API, converting errors into structured results.

    Letting ApiError propagate would surface as an opaque protocol-level
    failure. Returning the upstream status and message instead lets the
    client correct its own input -- a 404 for an unknown callsign or a 400
    for a bad filter is normal usage, not a server fault. A 429 likewise
    tells the client to slow down rather than that the tool is broken.
    """
    try:
        payload = await client.get(path, params)
    except ApiError as exc:
        return {"error": exc.detail, "status_code": exc.status_code}
    return payload if isinstance(payload, dict) else {"items": payload}


def _error(message: str) -> dict:
    return {"error": message}
