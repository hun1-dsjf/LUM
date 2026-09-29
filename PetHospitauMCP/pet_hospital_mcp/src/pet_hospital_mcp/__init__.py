"""Pet Hospital MCP — exposes the Go Pet Hospital REST API to AI agents.

Built on the official MCP Python SDK 2.x (``mcp==2.0.0``) using
``MCPServer`` in stateless Streamable HTTP mode (protocol ``2026-07-28``).

This package intentionally does NOT use ``mcp.server.fastmcp.FastMCP``
(removed/renamed in SDK 2.x) and does NOT implement the legacy
``initialize`` handshake, ``Mcp-Session-Id``, or session storage.
"""

__version__ = "0.1.0"

# Protocol / SDK identifiers re-exported for convenience and for tests.
MCP_SDK_VERSION = "2.0.0"
MCP_HTTP_PATH = "/mcp"

# Pull the actual protocol version from the installed SDK so it always tracks
# ``mcp==2.0.0``; fall back to the known value if the import path moves.
try:  # pragma: no cover - import guard
    from mcp.types import LATEST_PROTOCOL_VERSION as _LATEST_PROTOCOL_VERSION

    MCP_PROTOCOL_VERSION = _LATEST_PROTOCOL_VERSION
except Exception:  # pragma: no cover
    MCP_PROTOCOL_VERSION = "2026-07-28"
