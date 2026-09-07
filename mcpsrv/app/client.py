"""Thin async HTTP client for the FCC ULS Explorer REST API.

Deliberately contains no SQL and opens no database connection. Every MCP
tool is a passthrough to the existing `api` service, so query logic,
input validation, rate limiting and connection pooling all stay in exactly
one place rather than being reimplemented (and allowed to drift) here.

Uses httpx2, not httpx: the MCP SDK depends on httpx2 (Pydantic's
continuation of httpx under a new distribution and import name), so
pulling in plain httpx as well would mean shipping two HTTP stacks in one
image for no benefit.
"""
from typing import Any

import httpx2

from .config import settings


class ApiError(RuntimeError):
    """Raised when the REST API returns a non-success response.

    Carries the upstream status so tools can translate the API's own
    validation errors into messages an LLM client can act on, instead of
    surfacing an opaque failure.
    """

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"API returned {status_code}: {detail}")


class ApiClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self._client: httpx2.AsyncClient | None = None

    async def _get_client(self) -> httpx2.AsyncClient:
        if self._client is None:
            self._client = httpx2.AsyncClient(
                base_url=self.base_url,
                timeout=settings.request_timeout_seconds,
                # This client only ever talks to the internal API service on
                # the container network; a redirect would mean something is
                # badly misconfigured, so don't quietly follow one.
                follow_redirects=False,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """GET `path`, dropping None-valued params so callers can pass
        optional filters through unconditionally."""
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        client = await self._get_client()
        try:
            resp = await client.get(path, params=clean)
        except httpx2.RequestError as exc:
            raise ApiError(503, f"Could not reach the ULS API: {exc}") from exc

        if resp.status_code >= 400:
            raise ApiError(resp.status_code, _extract_detail(resp))
        return resp.json()


def _extract_detail(resp: "httpx2.Response") -> str:
    """Pull FastAPI's `detail` out of an error body when present.

    FastAPI uses `detail` for both plain strings (HTTPException) and lists
    of field errors (422 validation), so both shapes are handled; anything
    else falls back to the raw body.
    """
    try:
        body = resp.json()
    except Exception:
        return resp.text[:500]

    if isinstance(body, dict) and "detail" in body:
        detail = body["detail"]
        if isinstance(detail, str):
            return detail
        return str(detail)[:500]
    return str(body)[:500]


client = ApiClient()
