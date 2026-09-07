"""Live end-to-end check of the deployed MCP server over the public HTTPS
endpoint, driven by the real MCP SDK client (not hand-rolled JSON-RPC), so it
exercises the same path an LLM client would.

Run against production:
    podman exec mcp python3 live_check.py https://<host>/mcp
"""
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL = sys.argv[1] if len(sys.argv) > 1 else "https://fcculs-explorer.n00tz.net/mcp"

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

failures = []


def check(label, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + label + (f"  :: {detail}" if detail else ""))
    if not cond:
        failures.append(label)


def payload(result):
    sc = getattr(result, "structured_content", None)
    if isinstance(sc, dict):
        return sc.get("result", sc)
    if sc is not None:
        return sc
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except Exception:
                return text
    return None


async def main():
    async with streamable_http_client(URL) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"\nServer:   {init.server_info.name} v{init.server_info.version}")
            print(f"Protocol: {init.protocol_version}\n")

            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            print(f"Tools ({len(names)}): {', '.join(sorted(names))}\n")
            check("expected tool set advertised", EXPECTED_TOOLS <= names,
                  f"missing={sorted(EXPECTED_TOOLS - names)}")

            print("-- search_uls --")
            r = await session.call_tool("search_uls", {"query": "W1AW"})
            d = payload(r)
            results = (d or {}).get("results", []) if isinstance(d, dict) else []
            check("search returned results", not r.is_error and results, str(d)[:160])
            if results:
                print(f"      first: {results[0].get('result_type')} "
                      f"{results[0].get('key')} :: {results[0].get('label')}")

            print("-- get_license(amateur, W1AW) --")
            r = await session.call_tool("get_license", {"service": "amateur", "call_sign": "W1AW"})
            d = payload(r)
            ok = isinstance(d, dict) and not r.is_error
            hd = (d or {}).get("header") or {} if ok else {}
            en = (d or {}).get("entity") or {} if ok else {}
            check("W1AW resolved with a header", bool(hd), str(d)[:200])
            frn = en.get("frn")
            print(f"      status={hd.get('license_status')} "
                  f"class={hd.get('operator_class')} frn={frn}")

            if frn:
                print("-- get_identity_by_frn (cross-service grouping) --")
                r = await session.call_tool("get_identity_by_frn", {"frn": frn})
                d = payload(r)
                members = (d or {}).get("members", []) if isinstance(d, dict) else []
                check("FRN grouping returned members", not r.is_error and members, str(d)[:160])
                print(f"      sources: {sorted({m.get('source') for m in members})}")

            print("-- browse_licenses across all four services --")
            for svc in ("amateur", "gmrs", "aircraft", "ship"):
                r = await session.call_tool("browse_licenses", {"service": svc, "page_size": 3})
                d = payload(r)
                items = (d or {}).get("items", []) if isinstance(d, dict) else []
                check(f"browse_licenses({svc}) returned rows",
                      not r.is_error and items, str(d)[:140])
                if items:
                    print(f"      {svc}: total={(d or {}).get('total')} "
                          f"first={items[0].get('call_sign')}")

            print("-- browse_towers --")
            r = await session.call_tool("browse_towers", {"page_size": 3})
            d = payload(r)
            items = (d or {}).get("items", []) if isinstance(d, dict) else []
            check("browse_towers returned rows", not r.is_error and items, str(d)[:140])

            print("-- page_size bound enforced --")
            r = await session.call_tool("browse_licenses",
                                        {"service": "amateur", "page_size": 9999})
            d = payload(r)
            n = len((d or {}).get("items", [])) if isinstance(d, dict) else 0
            check("oversized page_size rejected or clamped", r.is_error or n <= 50,
                  f"is_error={r.is_error} items={n}")

            print("-- service-specific filter routed only to its own service --")
            r = await session.call_tool("browse_licenses",
                                        {"service": "aircraft", "n_number": "N1", "page_size": 3})
            check("aircraft n_number filter accepted", not r.is_error, str(payload(r))[:140])
            r = await session.call_tool("browse_licenses",
                                        {"service": "gmrs", "n_number": "N1", "page_size": 3})
            d = payload(r)
            check("gmrs ignores aircraft-only n_number (not a hard error)",
                  not r.is_error, str(d)[:140])

            print("-- describe_code --")
            r = await session.call_tool("describe_code",
                                        {"category": "operator_class", "code": "E"})
            d = payload(r)
            check("operator_class E describes Amateur Extra",
                  "extra" in str(d).lower(), str(d)[:140])

            print("-- list_field_definitions --")
            r = await session.call_tool("list_field_definitions", {})
            check("field definitions returned", not r.is_error, str(payload(r))[:120])

            print("-- get_new_hams --")
            r = await session.call_tool("get_new_hams", {"page_size": 3})
            d = payload(r)
            check("get_new_hams responded", not r.is_error, str(d)[:140])
            if isinstance(d, dict):
                print(f"      individuals={d.get('total_individuals')} "
                      f"clubs={d.get('total_clubs')}")

            print("-- get_change_history --")
            r = await session.call_tool("get_change_history",
                                        {"subject_key": "W1AW"})
            d = payload(r)
            check("change history returned an items list, not an argument error",
                  not r.is_error and isinstance(d, dict) and "items" in d, str(d)[:160])

            print("-- get_change_history with neither argument is rejected --")
            r = await session.call_tool("get_change_history", {})
            d = payload(r)
            check("missing subject_key/frn surfaced as an error",
                  isinstance(d, dict) and "error" in d, str(d)[:140])

            print("-- unknown callsign degrades to structured error, not a crash --")
            r = await session.call_tool("get_license",
                                        {"service": "amateur", "call_sign": "ZZ9ZZZ"})
            d = payload(r)
            check("404 surfaced as {error, status_code}",
                  isinstance(d, dict) and "error" in d, str(d)[:140])

            print("-- invalid enum rejected by schema validation --")
            r = await session.call_tool("browse_licenses", {"service": "not_a_service"})
            check("bad service enum rejected", r.is_error, str(payload(r))[:140])

    print()
    if failures:
        print(f"FAILED ({len(failures)}): {failures}")
        return 1
    print("ALL LIVE CHECKS PASSED")
    return 0


sys.exit(asyncio.run(main()))
