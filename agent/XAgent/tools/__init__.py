"""
工具包：文件操作 + 时间/闰年 + 联网搜索 + 网页抓取 + CLI 执行 + Skill 加载 + MCP Server 代理 + 上下文检索。

使用方式：
  # 静态导入（仅本地工具）—— Agent 已支持动态覆盖，这只是默认值
  from tools import TOOLS_SCHEMA, TOOL_MAP

  # 完整构建（本地 + MCP）—— main.py 启动时使用
  from tools import build_full_tools
  schemas, tool_map, mcp_mgr = build_full_tools()
"""
from __future__ import annotations

from typing import Callable

from .file_ops import TOOLS_SCHEMA as FILE_TOOLS_SCHEMA, TOOL_MAP as FILE_TOOL_MAP
from .time_ops import TOOLS_SCHEMA as TIME_TOOLS_SCHEMA, TOOL_MAP as TIME_TOOL_MAP
from .web_search import SEARCH_TOOLS_SCHEMA, SEARCH_TOOL_MAP
from .fetch_web import FETCH_TOOLS_SCHEMA, FETCH_TOOL_MAP
from .cli_ops import CLI_TOOLS_SCHEMA, CLI_TOOL_MAP
from .skill_ops import SKILL_TOOLS_SCHEMA, SKILL_TOOL_MAP
from .context_ops import CONTEXT_TOOLS_SCHEMA, CONTEXT_TOOL_MAP
from .mcp_client import MCPServerManager, build_mcp_tool_registry

# ---------- 本地静态工具（默认值）----------
TOOLS_SCHEMA: list[dict] = (
    FILE_TOOLS_SCHEMA
    + TIME_TOOLS_SCHEMA
    + SEARCH_TOOLS_SCHEMA
    + FETCH_TOOLS_SCHEMA
    + CLI_TOOLS_SCHEMA
    + SKILL_TOOLS_SCHEMA
    + CONTEXT_TOOLS_SCHEMA
)

TOOL_MAP: dict[str, Callable[[dict], str]] = {
    **FILE_TOOL_MAP,
    **TIME_TOOL_MAP,
    **SEARCH_TOOL_MAP,
    **FETCH_TOOL_MAP,
    **CLI_TOOL_MAP,
    **SKILL_TOOL_MAP,
    **CONTEXT_TOOL_MAP,
}


def build_full_tools() -> tuple[list[dict], dict[str, Callable[[dict], str]], MCPServerManager]:
    """构建完整工具集合 = 本地工具 + MCP Server 发现的工具。

    Returns:
        (schemas, tool_map, mcp_manager) —— 可直接传入 Agent 构造函数
    """
    mcp_schemas, mcp_map, mgr = build_mcp_tool_registry()
    all_schemas = TOOLS_SCHEMA + mcp_schemas
    all_map = {**TOOL_MAP, **mcp_map}
    return all_schemas, all_map, mgr


__all__ = ["TOOLS_SCHEMA", "TOOL_MAP", "build_full_tools", "MCPServerManager"]
