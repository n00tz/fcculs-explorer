"""End-to-end integration test for the MCP server.

Speaks the real MCP protocol over streamable HTTP to a real running MCP
server, which in turn calls a real `api` container backed by a real
Postgres. Nothing here is mocked: the point is to prove the whole chain
works, including the transport-security and proxy-header configuration
that unit tests cannot exercise.

Run via tests/run_integration.sh, which stands up the whole stack.
"""
import asyncio
import json
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_URL = os.environ.get("MCP_TEST_URL", "http://localhost:8080/mcp")

EXPECTED_TOOLS = {
    "search_uls",
    "browse_licenses",
    "browse_towers",
    "get_license",
    "get_tower",
    "get_identity_by_frn",
    "get_identity_by_address",
    "get_change_history",
    "get_new_hams",
    "describe_code",
    "list_field_definitions",
}


def payload(result) -> dict:
    """Pull the JSON body out of an MCP tool result."""
    if getattr(result, "structured_content", None):
        return result.structured_content
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"No usable content in tool result: {result!r}")


async def main() -> None:
    async with streamable_http_client(MCP_URL) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print("MCP session initialized OK")

            # --- tool discovery ---
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert names == EXPECTED_TOOLS, f"unexpected tools: {names ^ EXPECTED_TOOLS}"
            print(f"tool discovery OK: {len(names)} tools")

            # --- search across services ---
            result = await session.call_tool("search_uls", {"query": "N0OTZ"})
            body = payload(result)
            assert body["results"], body
            # Search returns result_type/key/label triples; `key` is the
            # callsign or ASR registration number.
            assert any(r["key"] == "N0OTZ" for r in body["results"]), body
            print("search_uls OK")

            # --- detail per service, proving the service routing works ---
            for service, callsign in (
                ("amateur", "N0OTZ"),
                ("gmrs", "WRAA123"),
                ("aircraft", "N123AB"),
                ("ship", "WDF1234"),
            ):
                result = await session.call_tool(
                    "get_license", {"service": service, "call_sign": callsign}
                )
                body = payload(result)
                assert "error" not in body, (service, body)
                assert body["header"]["call_sign"] == callsign, body
                print(f"get_license({service}) OK")

            # Service-specific detail sections must actually come through.
            body = payload(
                await session.call_tool(
                    "get_license", {"service": "ship", "call_sign": "WDF1234"}
                )
            )
            assert body["ship_specific"]["ship_name"] == "SEA TESTER", body
            voyages = body["voyages"]
            assert [v["voyage_number"] for v in voyages] == ["1", "2"], voyages
            print("ship-specific sections + voyage ordering OK")

            body = payload(
                await session.call_tool(
                    "get_license", {"service": "aircraft", "call_sign": "N123AB"}
                )
            )
            assert body["aircraft_specific"]["n_number"] == "N123AB", body
            print("aircraft-specific section OK")

            # --- a genuinely missing record is DATA, not a crash ---
            body = payload(
                await session.call_tool(
                    "get_license", {"service": "amateur", "call_sign": "ZZ9ZZZ"}
                )
            )
            assert body.get("status_code") == 404, body
            print("unknown callsign returns a structured 404 OK")

            # --- browse + filters ---
            body = payload(
                await session.call_tool(
                    "browse_licenses", {"service": "amateur", "state": "GA"}
                )
            )
            assert body["total"] >= 2, body
            print("browse_licenses OK")

            # Aircraft-only filter must reach the aircraft endpoint.
            body = payload(
                await session.call_tool(
                    "browse_licenses", {"service": "aircraft", "n_number": "N123"}
                )
            )
            assert body["total"] == 1, body
            print("browse_licenses aircraft n_number filter OK")

            # ...and must not be forwarded to a service that would reject it.
            body = payload(
                await session.call_tool(
                    "browse_licenses", {"service": "gmrs", "n_number": "N123"}
                )
            )
            assert "error" not in body, body
            print("service-specific filter isolation OK")

            body = payload(await session.call_tool("browse_towers", {"state": "TN"}))
            assert body["total"] >= 1, body
            print("browse_towers OK")

            body = payload(
                await session.call_tool("get_tower", {"registration_number": "1234567"})
            )
            assert body["registration"]["registration_number"] == "1234567", body
            print("get_tower OK")

            # --- identity grouping spanning services ---
            body = payload(
                await session.call_tool("get_identity_by_frn", {"frn": "0001112223"})
            )
            members = body["members"]
            # This FRN deliberately spans services in the seed data (two
            # amateur licences plus a GMRS one), which is the whole point of
            # cross-service identity grouping.
            assert len(members) >= 3, body
            kinds = {m.get("source") for m in members}
            assert kinds >= {"amateur", "gmrs"}, f"expected multiple services, got {kinds}"
            print(f"get_identity_by_frn OK ({len(members)} members across {kinds})")

            body = payload(
                await session.call_tool(
                    "get_identity_by_address",
                    {
                        "street_address": "100 Test Rd",
                        "city": "RINGGOLD",
                        "state": "GA",
                        "zip_code": "30736",
                    },
                )
            )
            assert "error" not in body, body
            print("get_identity_by_address OK")

            # --- change history ---
            body = payload(
                await session.call_tool("get_change_history", {"subject_key": "WRAA123"})
            )
            assert body["total"] == 1, body
            assert body["items"][0]["service"] == "gmrs", body
            print("get_change_history by subject_key OK")

            body = payload(
                await session.call_tool("get_change_history", {"frn": "0001112223"})
            )
            assert body["total"] >= 1, body
            print("get_change_history by frn OK")

            # The tool must refuse this itself rather than fetching everything.
            body = payload(await session.call_tool("get_change_history", {}))
            assert "error" in body, body
            print("get_change_history requires an identifier OK")

            # --- new hams ---
            body = payload(await session.call_tool("get_new_hams", {}))
            assert "total_individuals" in body, body
            assert "total_clubs" in body, body
            print(
                "get_new_hams OK "
                f"({body['total_individuals']} individuals, {body['total_clubs']} clubs)"
            )

            # --- code decoding ---
            body = payload(
                await session.call_tool(
                    "describe_code", {"category": "license_status", "code": "A"}
                )
            )
            assert body["description"] == "Active", body
            print("describe_code OK")

            # An unlisted code is null, not an error -- so the client reports
            # the raw code instead of inventing a meaning for it.
            body = payload(
                await session.call_tool(
                    "describe_code", {"category": "license_status", "code": "QQ"}
                )
            )
            assert body["description"] is None, body
            print("describe_code unmapped -> null OK")

            body = payload(await session.call_tool("list_field_definitions", {}))
            assert len(body["field_help"]) > 50, len(body["field_help"])
            print(f"list_field_definitions OK ({len(body['field_help'])} fields)")

            # --- schema constraints are enforced by the server ---
            result = await session.call_tool(
                "browse_licenses", {"service": "amateur", "page_size": 9999}
            )
            assert result.is_error, "page_size ceiling was not enforced"
            print("page_size ceiling enforced OK")

            result = await session.call_tool(
                "get_license", {"service": "cb-radio", "call_sign": "N0OTZ"}
            )
            assert result.is_error, "service enum was not enforced"
            print("service enum enforced OK")

    print("ALL MCP INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except AssertionError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        raise
