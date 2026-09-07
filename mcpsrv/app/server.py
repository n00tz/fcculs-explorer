"""MCP server entrypoint for FCC ULS Explorer.

Exposes the app's read-only data as MCP tools over streamable HTTP, so any
MCP-capable client or agent can query FCC licence data conversationally.

Read-only by design: no watch creation, no notification channels, no admin
actions. That keeps this surface exactly as public as the REST API's own
anonymous browse/search endpoints, so it needs no authentication model of
its own.
"""
import contextlib
import logging

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from .client import client
from .config import settings
from .tools import register_tools

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
Query United States FCC radio licence data: Amateur radio, GMRS, Aircraft,
Ship, and registered antenna structures (towers).

Guidance:
- If you don't know which service a callsign belongs to, start with
  search_uls; each result's `result_type` tells you which detail tool to
  call next.
- FCC data uses short codes (e.g. status "A", operator class "E"). Use
  describe_code to translate them rather than guessing -- the same letter
  means different things in different fields.
- get_identity_by_frn is the best way to see everything one person or
  organization holds, since a single FRN often covers several services.
- This data comes from the FCC's public daily and weekly transaction
  files and is refreshed daily. It is a mirror, not an authoritative
  source, and it contains no private information beyond what the FCC
  itself publishes.
"""


def build_server() -> MCPServer:
    mcp = MCPServer(
        name="fcculs-explorer",
        title="FCC ULS Explorer",
        version="1.0.0",
        instructions=INSTRUCTIONS,
    )
    register_tools(mcp)
    return mcp


def build_app():
    mcp = build_server()

    # DNS-rebinding protection must be configured EXPLICITLY here, because
    # both of the SDK's implicit behaviours are wrong for this deployment:
    #   * Passing nothing makes streamable_http_app() auto-arm a
    #     localhost-only Host allowlist (its `host` default is 127.0.0.1),
    #     so every request arriving through Caddy under the real hostname
    #     is rejected with 421 Misdirected Request -- logged server-side
    #     only, with nothing useful shown to the client.
    #   * TransportSecuritySettings() on its own defaults to protection
    #     ENABLED with an EMPTY allowlist, which rejects everything.
    # Caddy terminates and controls the Host header, so the protection is
    # redundant here and is disabled deliberately rather than by accident.
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=settings.enable_dns_rebinding_protection
    )

    app = mcp.streamable_http_app(
        streamable_http_path=settings.mount_path,
        transport_security=security,
        # Return whole JSON responses instead of holding an SSE stream open
        # per call. Simpler for clients and avoids buffering issues through
        # the proxy chain; nothing here streams partial results anyway.
        json_response=True,
    )

    # Close the shared httpx2 client on shutdown, chained onto the SDK's own
    # lifespan rather than replacing it -- the transport's session manager
    # starts in that lifespan, and losing it yields "Task group is not
    # initialized" on the first request.
    sdk_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with sdk_lifespan(app):
            try:
                yield
            finally:
                await client.aclose()

    app.router.lifespan_context = lifespan
    return app


def main() -> None:
    logger.info(
        "Starting MCP server on %s:%s%s (API base %s)",
        settings.host,
        settings.port,
        settings.mount_path,
        settings.api_base_url,
    )
    uvicorn.run(
        build_app(),
        host=settings.host,
        port=settings.port,
        # Honour X-Forwarded-Proto from Caddy. Without this the SDK's
        # /mcp -> /mcp/ redirect is issued as http://, and MCP clients
        # refuse to follow a downgrade, so the connection just fails.
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=False,
    )


if __name__ == "__main__":
    main()
