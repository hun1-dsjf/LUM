"""MCP server assembly.

Builds an :class:`mcp.server.MCPServer` in **stateless Streamable HTTP** mode
(SDK 2.x, protocol ``2026-07-28``), registers the ``list_pets`` tool, exposes a
``/health`` endpoint on the same ASGI app, and exports the resulting Starlette
app for both production (``uvicorn pet_hospital_mcp.server:app``) and tests.

Key properties (verified against the official SDK 2.0.0 docs):
  * No ``initialize`` handshake, no ``Mcp-Session-Id``, no session storage.
  * ``stateless_http=True`` + ``json_response=True``: each POST gets a single
    JSON body response; a fresh transport per request.
  * ``@mcp.custom_route("/health")`` registers an unauthenticated route on the
    same app (health checks must be reachable pre-auth by design).
"""

from __future__ import annotations

from typing import Any

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse

from . import (
    MCP_HTTP_PATH,
    MCP_PROTOCOL_VERSION,
    MCP_SDK_VERSION,
    __version__ as pkg_version,
)
from .config import load_config
from .logging_config import configure_logging, get_logger
from .tools import register_list_pets

log = get_logger("pet_hospital_mcp.server")

# Server name advertised to MCP clients.
SERVER_NAME = "Pet Hospital MCP"


def create_mcp() -> MCPServer:
    """Construct the MCPServer and register tools."""
    mcp = MCPServer(SERVER_NAME)
    register_list_pets(mcp)
    return mcp


def _health_payload() -> dict[str, Any]:
    cfg = load_config()
    return {
        "status": "ok",
        "service": SERVER_NAME,
        "version": pkg_version,
        "mcp_sdk_version": MCP_SDK_VERSION,
        "mcp_protocol_version": MCP_PROTOCOL_VERSION,
        "transport": "streamable-http (stateless)",
        "mcp_endpoint": cfg.mcp_url,
        "backend_base_url": cfg.backend_base_url,
    }


def create_app() -> Any:
    """Build the ASGI app: ``/mcp`` (MCP) + ``/health`` + ``/favicon.ico``."""
    configure_logging()
    mcp = create_mcp()

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse(_health_payload())

    @mcp.custom_route("/favicon.ico", methods=["GET"])
    async def favicon(request: Request) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"ok": True}, status_code=204)

    app = mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        streamable_http_path=MCP_HTTP_PATH,
    )
    # Keep handles for tests / inspection.
    app.mcp = mcp  # type: ignore[attr-defined]
    app.mcp_server = mcp  # type: ignore[attr-defined]
    return app


# Module-level ASGI app for ``uvicorn pet_hospital_mcp.server:app``.
app = create_app()
