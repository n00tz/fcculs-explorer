"""Environment-driven configuration for the MCP server.

Follows the notifier's plain-dataclass-over-os.environ pattern rather than
api's pydantic-settings: this service has a handful of scalar settings and
no validation needs beyond int/bool coercion, so the extra dependency would
buy nothing. The shared project convention is the FCCULS_ env prefix, not
the mechanism.
"""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    # The MCP server holds no database credentials and opens no database
    # connections -- every tool is a passthrough to the REST API, which
    # already owns query logic, validation and rate limiting.
    api_base_url: str = os.environ.get(
        "FCCULS_API_BASE_URL", "http://localhost:8000"
    ).rstrip("/")

    host: str = os.environ.get("FCCULS_MCP_HOST", "0.0.0.0")
    port: int = int(os.environ.get("FCCULS_MCP_PORT", "8080"))

    # Mount path for the streamable-HTTP transport. Caddy proxies both this
    # and its trailing-slash form; see the deployment notes in the README.
    mount_path: str = os.environ.get("FCCULS_MCP_MOUNT_PATH", "/mcp")

    # The SDK auto-arms a localhost-only Host allowlist when no explicit
    # transport security is configured AND the configured host is loopback,
    # which behind a reverse proxy yields 421 Misdirected Request with no
    # client-visible explanation. This service runs behind Caddy, which
    # controls the Host header, so DNS-rebinding protection is disabled
    # deliberately and explicitly rather than left to that default.
    enable_dns_rebinding_protection: bool = (
        os.environ.get("FCCULS_MCP_DNS_REBINDING_PROTECTION", "false").lower() == "true"
    )

    request_timeout_seconds: float = float(
        os.environ.get("FCCULS_MCP_REQUEST_TIMEOUT_SECONDS", "30")
    )

    # Tool results are consumed by LLMs with finite context windows, so the
    # default page size is deliberately smaller than the REST API's own.
    default_page_size: int = int(os.environ.get("FCCULS_MCP_DEFAULT_PAGE_SIZE", "10"))
    max_page_size: int = int(os.environ.get("FCCULS_MCP_MAX_PAGE_SIZE", "50"))


settings = Settings()
