"""MCP tools package. Each new tool lives in its own module and exposes
``register(mcp_server)`` so the server wires it up without touching tool
internals.
"""

from .list_pets import register as register_list_pets

__all__ = ["register_list_pets"]
