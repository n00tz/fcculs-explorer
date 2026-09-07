"""Unit tests for the MCP tool layer.

These cover the parts that are genuinely this service's own logic rather
than the REST API's: tool schema generation (which is the entire contract
an LLM client sees), error translation, and the service-specific filter
routing. Real data behavior is covered by integration_test.py against a
live API -- these deliberately do not mock away the thing under test.
"""
import asyncio

import pytest

from app import tools as tools_mod
from app.client import ApiError
from app.server import build_server


@pytest.fixture(scope="module")
def registered_tools():
    mcp = build_server()
    return {t.name: t for t in asyncio.run(mcp.list_tools())}


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


def test_all_expected_tools_are_registered(registered_tools):
    assert set(registered_tools) == EXPECTED_TOOLS


def test_every_tool_has_a_description(registered_tools):
    # The description IS the interface: an LLM picks tools by reading it,
    # so an empty one silently makes a tool unusable rather than failing.
    for name, tool in registered_tools.items():
        assert (tool.description or "").strip(), f"{name} has no description"


def test_required_arguments_are_correct(registered_tools):
    assert registered_tools["get_license"].input_schema["required"] == [
        "service",
        "call_sign",
    ]
    assert registered_tools["search_uls"].input_schema["required"] == ["query"]
    # Both identifiers are optional here on purpose; the tool enforces
    # "at least one" itself, which a JSON Schema `required` list can't say.
    assert registered_tools["get_change_history"].input_schema.get("required", []) == []


def test_service_argument_is_constrained_to_known_services(registered_tools):
    for name in ("browse_licenses", "get_license"):
        schema = registered_tools[name].input_schema["properties"]["service"]
        assert set(schema["enum"]) == set(tools_mod.SERVICE_PATHS)


def test_page_size_is_bounded(registered_tools):
    # Unbounded results would blow out a client's context window; the MCP
    # protocol imposes no cap of its own, so the schema must.
    for name in ("browse_licenses", "browse_towers", "get_change_history", "get_new_hams"):
        schema = registered_tools[name].input_schema["properties"]["page_size"]
        assert schema["minimum"] == 1
        assert schema["maximum"] == tools_mod.settings.max_page_size


def test_service_paths_cover_every_license_service():
    assert set(tools_mod.SERVICE_PATHS) == {"amateur", "gmrs", "aircraft", "ship"}
    for service, path in tools_mod.SERVICE_PATHS.items():
        assert path.startswith("/api/"), service


def test_unknown_service_is_rejected():
    with pytest.raises(ValueError):
        tools_mod._service_path("cb-radio")


def test_api_errors_become_structured_results(monkeypatch):
    # A 404 for an unknown callsign is normal usage, not a server fault:
    # it must come back as data the client can act on, not as a protocol
    # error that just looks like the tool is broken.
    async def boom(path, params=None):
        raise ApiError(404, "Callsign not found")

    monkeypatch.setattr(tools_mod.client, "get", boom)
    result = asyncio.run(tools_mod._get("/api/amateur/NOPE"))
    assert result == {"error": "Callsign not found", "status_code": 404}


def test_non_dict_payloads_are_wrapped(monkeypatch):
    async def listy(path, params=None):
        return [1, 2, 3]

    monkeypatch.setattr(tools_mod.client, "get", listy)
    assert asyncio.run(tools_mod._get("/whatever")) == {"items": [1, 2, 3]}


def _capture_requests(monkeypatch):
    """Record the path/params each tool sends to the REST API."""
    calls = []

    async def record(path, params=None):
        calls.append((path, params or {}))
        return {}

    monkeypatch.setattr(tools_mod.client, "get", record)
    return calls


def test_service_specific_filters_only_go_to_their_own_service(monkeypatch):
    # The API rejects unknown query params, so forwarding n_number to the
    # GMRS endpoint (or operator_class to Ship) would turn an ignorable
    # argument into a hard failure.
    mcp = build_server()
    calls = _capture_requests(monkeypatch)

    asyncio.run(
        mcp.call_tool(
            "browse_licenses",
            {"service": "aircraft", "n_number": "N123AB", "operator_class": "E"},
        )
    )
    path, params = calls[-1]
    assert path == "/api/aircraft"
    assert params["n_number"] == "N123AB"
    assert "class" not in params, "amateur-only filter leaked to aircraft"
    assert "ship_name" not in params

    asyncio.run(
        mcp.call_tool(
            "browse_licenses", {"service": "gmrs", "n_number": "N123AB", "state": "GA"}
        )
    )
    path, params = calls[-1]
    assert path == "/api/gmrs"
    assert params["state"] == "GA"
    assert "n_number" not in params, "aircraft-only filter leaked to gmrs"

    asyncio.run(
        mcp.call_tool("browse_licenses", {"service": "amateur", "operator_class": "E"})
    )
    path, params = calls[-1]
    assert path == "/api/amateur"
    # The API exposes operator class under the `class` alias.
    assert params["class"] == "E"


def test_callsign_is_normalized_before_lookup(monkeypatch):
    mcp = build_server()
    calls = _capture_requests(monkeypatch)
    asyncio.run(mcp.call_tool("get_license", {"service": "amateur", "call_sign": " n0otz "}))
    assert calls[-1][0] == "/api/amateur/N0OTZ"


def test_change_history_requires_an_identifier(monkeypatch):
    mcp = build_server()
    calls = _capture_requests(monkeypatch)
    result = asyncio.run(mcp.call_tool("get_change_history", {}))
    assert not calls, "should not have called the API without an identifier"
    assert "error" in str(result).lower()
