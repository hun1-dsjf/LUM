"""AnythingLLM MCP Server - HTTP transport, single tool MVP."""

import os
import json
import urllib.request

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()  # 从 .env 加载配置

ANYTHINGLLM_BASE = os.getenv("ANYTHINGLLM_BASE", "http://localhost:3001")
ANYTHINGLLM_API_KEY = os.getenv("ANYTHINGLLM_API_KEY", "")
ANYTHINGLLM_WORKSPACE_SLUG = os.getenv("ANYTHINGLLM_WORKSPACE_SLUG", "")

mcp = MCPServer("anythingllm-mcp")


def _get_first_workspace_slug() -> str:
    """Fetch the first workspace slug from AnythingLLM."""
    if ANYTHINGLLM_WORKSPACE_SLUG:
        return ANYTHINGLLM_WORKSPACE_SLUG
    req = urllib.request.Request(
        f"{ANYTHINGLLM_BASE}/api/v1/workspaces",
        headers={"Authorization": f"Bearer {ANYTHINGLLM_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    return data["workspaces"][0]["slug"]


@mcp.tool()
def query_workspace(message: str) -> str:
    """向 AnythingLLM 第一个工作区提问，返回 AI 回答。

    Args:
        message: 要向工作区提出的问题
    """
    slug = _get_first_workspace_slug()
    payload = json.dumps({"message": message, "mode": "chat"}).encode()
    req = urllib.request.Request(
        f"{ANYTHINGLLM_BASE}/api/v1/workspace/{slug}/chat",
        data=payload,
        headers={
            "Authorization": f"Bearer {ANYTHINGLLM_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())

    result = data.get("textResponse", "")
    sources = data.get("sources", [])
    if sources:
        names = [s.get("title", "?") for s in sources]
        result += "\n\n参考来源: " + ", ".join(names)

    return result


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
