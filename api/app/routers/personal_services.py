"""Browse/detail endpoints for the personal radio services that share the
generic ULS record layout: GMRS, Aircraft (Part 87) and Ship (Part 80).

These three services are deliberately served by ONE config-driven router
factory rather than three near-identical hand-written modules. The goal for
this feature was explicit -- users of these services should not be
second-class citizens next to Amateur -- and the surest way to guarantee
that is to make feature parity structural: every service automatically gets
the same rate limiting, the same allow-listed sorting, the same partial-match
filtering, and the same detail-page sections, because there is only one
implementation of each. Adding a fourth service is then a dict entry, not a
new file to keep in sync.

(Amateur keeps its own module: it has service-specific concepts -- operator
class, trustee/club relationships, the New Hams celebration -- that don't
generalize, and rewriting a live, working endpoint to fit a shared abstraction
would risk real user-facing data for no functional gain.)
"""
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from psycopg import AsyncConnection

from ..config import settings
from ..db import get_db
from ..history_codes import describe_history_code
from ..pagination import Page, PageParams, resolve_sort
from ..ratelimit import enforce_rate_limit


@dataclass(frozen=True)
class DetailSection:
    """An extra service-specific block returned by the detail endpoint."""

    key: str
    table: str
    # True when a subject legitimately has several rows (ship voyage
    # descriptions, which FCC splits across sequence-numbered rows).
    many: bool = False
    order_by: str | None = None


@dataclass(frozen=True)
class ServiceConfig:
    name: str
    prefix: str
    subject_type: str
    hd_table: str
    en_table: str
    hs_table: str
    # Extra JOIN applied to the browse query, aliased so browse_columns and
    # sortable_columns can reference it.
    browse_join: str = ""
    browse_columns: str = ""
    sortable_columns: dict[str, str] = field(default_factory=dict)
    # Extra browse filters: query-param name -> (SQL condition, kind).
    # kind "ilike" does partial matching; "exact" compares uppercased.
    extra_filters: dict[str, tuple[str, str]] = field(default_factory=dict)
    detail_sections: tuple[DetailSection, ...] = ()


BASE_SORTABLE = {
    "call_sign": "hd.call_sign",
    "license_status": "hd.license_status",
    "entity_name": "en.entity_name",
    "state": "en.state",
    "city": "en.city",
    "grant_date": "hd.grant_date",
    "expired_date": "hd.expired_date",
}

SERVICE_CONFIGS: dict[str, ServiceConfig] = {
    "gmrs": ServiceConfig(
        name="gmrs",
        prefix="/api/gmrs",
        subject_type="gmrs_license",
        hd_table="gmrs_hd",
        en_table="gmrs_en",
        hs_table="gmrs_hs",
        sortable_columns=dict(BASE_SORTABLE),
    ),
    "aircraft": ServiceConfig(
        name="aircraft",
        prefix="/api/aircraft",
        subject_type="aircraft_license",
        hd_table="aircr_hd",
        en_table="aircr_en",
        hs_table="aircr_hs",
        browse_join="LEFT JOIN aircr_ac ac ON ac.unique_system_identifier = hd.unique_system_identifier",
        browse_columns="ac.n_number, ac.type_of_carrier, ac.fleet_indicator",
        sortable_columns={
            **BASE_SORTABLE,
            "n_number": "ac.n_number",
            "type_of_carrier": "ac.type_of_carrier",
        },
        # The FAA tail number is how aircraft operators actually search.
        extra_filters={"n_number": ("ac.n_number ILIKE %(n_number)s", "ilike")},
        detail_sections=(DetailSection(key="aircraft_specific", table="aircr_ac"),),
    ),
    "ship": ServiceConfig(
        name="ship",
        prefix="/api/ship",
        subject_type="ship_license",
        hd_table="ship_hd",
        en_table="ship_en",
        hs_table="ship_hs",
        browse_join="LEFT JOIN ship_sh sh ON sh.unique_system_identifier = hd.unique_system_identifier",
        browse_columns="sh.ship_name, sh.general_class, sh.special_class, sh.station_number",
        sortable_columns={
            **BASE_SORTABLE,
            "ship_name": "sh.ship_name",
            "general_class": "sh.general_class",
        },
        extra_filters={
            "ship_name": ("sh.ship_name ILIKE %(ship_name)s", "ilike"),
            # station_number is the vessel's MMSI -- a primary real-world
            # identifier, so it gets its own filter.
            "mmsi": ("sh.station_number ILIKE %(mmsi)s", "ilike"),
        },
        detail_sections=(
            DetailSection(key="ship_specific", table="ship_sh"),
            DetailSection(key="radio_equipment", table="ship_sr"),
            DetailSection(
                key="voyages", table="ship_sv", many=True,
                # FCC splits one long description across sequence-numbered
                # rows; they must come back in order to read correctly.
                order_by="voyage_number",
            ),
            DetailSection(key="exemption_request", table="ship_se"),
        ),
    ),
}


def build_router(cfg: ServiceConfig) -> APIRouter:
    router = APIRouter(prefix=cfg.prefix, tags=[cfg.name])
    sortable = cfg.sortable_columns
    extra_cols = f", {cfg.browse_columns}" if cfg.browse_columns else ""

    @router.get("", response_model=Page)
    async def browse(
        request: Request,
        callsign: str | None = Query(None),
        name: str | None = Query(None),
        city: str | None = Query(None),
        state: str | None = Query(None),
        status_code: str | None = Query(None, alias="status"),
        n_number: str | None = Query(None),
        ship_name: str | None = Query(None),
        mmsi: str | None = Query(None),
        sort: str | None = Query(None, description=f"One of {sorted(sortable)}"),
        order: str | None = Query(None, description="asc or desc"),
        page_params: PageParams = Depends(),
        conn: AsyncConnection = Depends(get_db),
    ):
        sort_expr, sort_direction = resolve_sort(
            sort, order, sortable, default_column="call_sign"
        )
        client_ip = request.client.host if request.client else "unknown"
        await enforce_rate_limit(
            f"{cfg.name}-browse:{client_ip}",
            settings.rate_limit_search_max,
            settings.rate_limit_search_window_seconds,
        )

        conditions: list[str] = []
        params: dict = {}
        if callsign:
            conditions.append("hd.call_sign ILIKE %(callsign)s")
            params["callsign"] = f"%{callsign.strip()}%"
        if name:
            conditions.append(
                "(en.entity_name ILIKE %(name)s OR en.first_name ILIKE %(name)s"
                " OR en.last_name ILIKE %(name)s)"
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

        # Service-specific filters, ignored when the caller passes one that
        # doesn't apply to this service (e.g. ?ship_name= against /api/gmrs).
        supplied = {"n_number": n_number, "ship_name": ship_name, "mmsi": mmsi}
        for key, (condition, kind) in cfg.extra_filters.items():
            value = supplied.get(key)
            if not value:
                continue
            conditions.append(condition)
            params[key] = f"%{value.strip()}%" if kind == "ilike" else value.strip().upper()

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        from_clause = f"""
            FROM {cfg.hd_table} hd
            LEFT JOIN {cfg.en_table} en ON en.unique_system_identifier = hd.unique_system_identifier
            {cfg.browse_join}
        """

        async with conn.cursor() as cur:
            await cur.execute(
                f"SELECT count(*) AS total {from_clause} {where_clause}", params
            )
            total = (await cur.fetchone())["total"]

            await cur.execute(
                f"""
                SELECT hd.call_sign, hd.license_status, hd.radio_service_code,
                       hd.grant_date, hd.expired_date,
                       en.entity_name, en.state, en.city{extra_cols}
                {from_clause}
                {where_clause}
                ORDER BY {sort_expr} {sort_direction} NULLS LAST, hd.call_sign
                LIMIT %(limit)s OFFSET %(offset)s
                """,
                {**params, "limit": page_params.limit, "offset": page_params.offset},
            )
            rows = await cur.fetchall()

        return Page(
            items=rows, page=page_params.page,
            page_size=page_params.page_size, total=total,
        )

    @router.get("/{call_sign}")
    async def detail(
        request: Request,
        call_sign: str,
        conn: AsyncConnection = Depends(get_db),
    ):
        call_sign = call_sign.upper()
        client_ip = request.client.host if request.client else "unknown"
        await enforce_rate_limit(
            f"{cfg.name}-detail:{client_ip}",
            settings.rate_limit_search_max,
            settings.rate_limit_search_window_seconds,
        )

        async with conn.cursor() as cur:
            # A callsign can appear under several unique_system_identifiers
            # over time (reassigned after a prior licence lapsed). Resolve
            # the CURRENT holder -- prefer an active record, else the most
            # recently granted -- and scope every other section to that same
            # identifier so two holders' data is never blended.
            await cur.execute(
                f"""
                SELECT unique_system_identifier FROM {cfg.hd_table}
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

            await cur.execute(
                f"SELECT * FROM {cfg.hd_table} WHERE unique_system_identifier = %s", (usid,)
            )
            header = await cur.fetchone()

            await cur.execute(
                f"SELECT * FROM {cfg.en_table} WHERE unique_system_identifier = %s", (usid,)
            )
            entity = await cur.fetchone()

            sections: dict = {}
            for section in cfg.detail_sections:
                order_clause = f" ORDER BY {section.order_by}" if section.order_by else ""
                await cur.execute(
                    f"SELECT * FROM {section.table}"
                    f" WHERE unique_system_identifier = %s{order_clause}",
                    (usid,),
                )
                sections[section.key] = (
                    await cur.fetchall() if section.many else await cur.fetchone()
                )

            # Full history across ALL holders of the callsign, so the
            # timeline shows a prior holder's expiry then the new grant.
            await cur.execute(
                f"SELECT * FROM {cfg.hs_table} WHERE callsign = %s"
                " ORDER BY log_date DESC NULLS LAST",
                (call_sign,),
            )
            history = await cur.fetchall()
            for entry in history:
                entry["code_description"] = describe_history_code(entry.get("code"))

            await cur.execute(
                """
                SELECT field_name, old_value, new_value, source_file,
                       effective_date, detected_at
                FROM change_events
                WHERE subject_type = %s AND subject_key = %s
                ORDER BY detected_at DESC
                LIMIT 100
                """,
                (cfg.subject_type, call_sign),
            )
            change_log = await cur.fetchall()

            # Cross-service identity grouping: the headline reason these
            # services are worth adding together, since one FRN commonly
            # holds e.g. both an Amateur and a GMRS licence.
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
            "service": cfg.name,
            "header": header,
            "entity": entity,
            "history": history,
            "change_log": change_log,
            "related_identities": related,
            **sections,
        }

    return router


routers = [build_router(cfg) for cfg in SERVICE_CONFIGS.values()]
