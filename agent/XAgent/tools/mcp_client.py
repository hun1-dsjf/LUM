"""
MCP Client 适配器 —— 为 XAgent 提供 MCP Server 连接、工具发现与调用。

设计原则：
  - 每个 MCP Server 独占一个后台线程 + 一个专属 asyncio 事件循环
  - Transport（stdio / sse / streamable_http）和 ClientSession 在该循环内创建并长期驻留
  - 主线程通过 run_coroutine_threadsafe 跨线程调度 call_tool
  - 工具名统一加前缀 {server_name}_{tool_name}，避免多 Server 重名冲突
  - 单个 Server 连接失败不影响其他 Server，错误信息明确回传 LLM
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from config.config_manager import AGENT_CONFIG

# MCP SDK —— 延迟导入，避免未安装时主程序崩溃
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    from mcp.client.streamable_http import streamable_http_client
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


# ========== 配置加载 ==========

def _find_mcp_json() -> Path | None:
    """向上查找 .mcp.json，策略与 skill_loader 一致：从 os.getcwd() 向上 20 层。"""
    cursor = Path(os.getcwd()).resolve()
    for _ in range(20):
        candidate = cursor / ".mcp.json"
        if candidate.is_file():
            return candidate
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return None


def load_mcp_config() -> dict[str, Any]:
    """读取 .mcp.json。找不到返回空 dict，解析失败返回 {'__error__': ...}。"""
    path = _find_mcp_json()
    if path is None:
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as e:
        return {"__error__": f".mcp.json 解析失败: {e}"}

    if not isinstance(data, dict):
        return {"__error__": ".mcp.json 顶层必须是对象"}

    # 兼容多种 key 命名
    servers = data.get("servers") or data.get("mcpServers")
    if servers is None:
        servers = data  # 兜底：顶层直接放 server 配置

    if not isinstance(servers, dict):
        return {"__error__": ".mcp.json servers 必须是对象"}

    # URL 规范化（去反引号、trim）
    for sname, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        url = cfg.get("url")
        if isinstance(url, str):
            cfg["url"] = url.strip().strip("`").strip()

    return {"_path": str(path.resolve()), "servers": servers}


# ========== MCP Transport 工厂 ==========

def _make_transport(config: dict):
    """根据 config 返回一个 AsyncContextManager（不进入，由调用方持有）。

    返回值是一个 async context manager，进入后 yield (read_stream, write_stream)。
    调用方必须持有该 context manager 直到 session 结束，否则 transport 会立即关闭。
    """
    transport = (config.get("transport") or "stdio").lower()

    if transport == "stdio":
        cmd = config.get("command")
        if not cmd:
            raise ValueError("stdio 传输缺少 command 字段")
        params = StdioServerParameters(
            command=cmd,
            args=list(config.get("args", []) or []),
            env=config.get("env"),
            cwd=config.get("cwd"),
        )
        return stdio_client(params)

    elif transport in ("sse", "streamable_http"):
        url = config.get("url")
        if not url:
            raise ValueError(f"{transport} 传输缺少 url 字段")
        timeout = float(config.get("timeout", 10))
        headers = config.get("headers")
        if transport == "sse":
            return sse_client(url, headers=headers, timeout=timeout)
        return streamable_http_client(url)
    else:
        raise ValueError(f"未知传输类型: {transport}（支持 stdio / sse / streamable_http）")


# ========== MCP Server 后台管理器 ==========

class MCPServerManager:
    """管理所有 MCP Server 的连接、工具发现、工具调用桥接。"""

    def __init__(self):
        self._servers: dict[str, "_ServerHandle"] = {}
        self._tool_to_server: dict[str, str] = {}  # "server_tool" → server_name
        self._tool_map: dict[str, Callable[[dict], str]] = {}  # 工具名 → 同步调用函数
        self._tool_schemas: list[dict] = []  # OpenAI function calling schema

    @property
    def tool_map(self) -> dict[str, Callable[[dict], str]]:
        return self._tool_map

    @property
    def tool_schemas(self) -> list[dict]:
        return self._tool_schemas

    @property
    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    # ---------- 连接 ----------

    def connect_all(self, config: dict) -> list[str]:
        """根据 .mcp.json 的 servers 配置逐一连接。返回成功连接的 server 名列表。"""
        if not MCP_AVAILABLE:
            print("[MCP] mcp SDK 未安装，跳过 MCP 加载", file=sys.stderr, flush=True)
            return []

        servers_cfg = config.get("servers", {})
        ok: list[str] = []

        # 先并行启动所有 server 的后台线程，再统一等待，避免串行超时叠加
        pending: list[tuple[str, _ServerHandle]] = []
        for name, cfg in servers_cfg.items():
            print(f"[MCP] 正在连接 {name} ...", file=sys.stderr, flush=True)
            handle = _ServerHandle(name, cfg)
            handle.start(wait=False)
            pending.append((name, handle))

        deadline = time.monotonic() + max(5.0, float(AGENT_CONFIG.mcp_timeout))
        for name, handle in pending:
            try:
                remaining = max(0.5, deadline - time.monotonic())
                handle.wait_ready(timeout=remaining)
                self._servers[name] = handle
                ok.append(name)
                print(f"[MCP] ✅ {name} 已连接，发现 {len(handle.tools)} 个工具", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[MCP] ❌ {name} 连接失败: {e}", file=sys.stderr, flush=True)

        # 发现工具，构建 schema 和调用映射
        for sname, handle in self._servers.items():
            for tool in handle.tools:
                self._register_tool(sname, handle, tool)

        return ok

    def shutdown(self) -> None:
        for name, handle in list(self._servers.items()):
            try:
                handle.stop()
            except Exception:
                pass
        self._servers.clear()

    # ---------- 注册工具 ----------

    def _register_tool(self, server_name: str, handle: "_ServerHandle", tool) -> None:
        """把 MCP Tool 转成 OpenAI function calling schema + 同步调用包装。"""
        # 工具名 = {server_name}_{tool.name}，统一小写下划线
        safe_server = server_name.lower().replace("-", "_")
        safe_tool = tool.name.lower().replace("-", "_")
        full_name = f"{safe_server}_{safe_tool}"

        # 防冲突：如果已被占用（不太可能，但安全起见加后缀）
        base_name = full_name
        i = 1
        while full_name in self._tool_map:
            full_name = f"{base_name}_{i}"
            i += 1

        # Schema —— MCP Tool 的 input_schema 已经是标准 JSON Schema
        description = tool.description or ""
        description = f"[来自 MCP Server: {server_name}]\n{description}".strip()

        # Pydantic 2.x: model_dump(by_alias=True) 确保 JSON Schema 字段用 camelCase 别名
        tool_dump = tool.model_dump(by_alias=True, exclude={"name", "description"})

        schema = {
            "type": "function",
            "function": {
                "name": full_name,
                "description": description,
                "parameters": tool_dump.get("inputSchema", tool_dump.get("input_schema", {})),
            },
        }

        # 同步调用包装函数
        def _call_wrapper(args: dict, *, _h=handle, _tname=tool.name) -> str:
            return _h.call_tool_sync(_tname, args)

        self._tool_map[full_name] = _call_wrapper
        self._tool_schemas.append(schema)
        self._tool_to_server[full_name] = server_name


# ========== 单个 Server 的后台线程/事件循环封装 ==========

class _ServerHandle:
    """一个 MCP Server 的后台运行容器。

    - 创建专属线程 + asyncio 事件循环
    - 在事件循环内建立 transport + session
    - 主线程通过 call_tool_sync() 桥接到事件循环内执行 call_tool
    """

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.loop: asyncio.AbstractEventLoop | None = None
        self.session: ClientSession | None = None
        self.tools: list = []
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: str | None = None
        self._stop_event = threading.Event()
        self._cleanup_task: asyncio.Task | None = None

    def start(self, *, wait: bool = True, timeout: float = 15.0) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"MCP-{self.name}")
        self._thread.start()
        if wait:
            self.wait_ready(timeout)

    def wait_ready(self, timeout: float = 15.0) -> None:
        """等待后台线程完成 initialize + list_tools。"""
        if not self._ready.wait(timeout=timeout):
            raise RuntimeError(
                f"MCP Server '{self.name}' 启动超时" + (f": {self._error}" if self._error else "")
            )
        if self._error:
            raise RuntimeError(f"MCP Server '{self.name}' 启动失败: {self._error}")

    def _run(self) -> None:
        """后台线程主函数：创建事件循环 → 连接 → 初始化 → run_forever → 清理。"""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def _bootstrap_and_wait():
            try:
                await self._connect_and_init()
                self._ready.set()
                # 在 event loop 内等待 threading.Event（阻塞等待，让出执行权）
                await self.loop.run_in_executor(None, self._stop_event.wait)
            except Exception as e:
                self._error = f"{type(e).__name__}: {e}"
                traceback.print_exc(file=sys.stderr)
            finally:
                try:
                    await self._disconnect()
                except Exception:
                    pass
                self.loop.call_soon(self.loop.stop)

        try:
            self.loop.create_task(_bootstrap_and_wait())
            self.loop.run_forever()
        finally:
            self.loop.close()

    async def _connect_and_init(self) -> None:
        """建立 transport → 进入 ClientSession context → initialize → list_tools。"""
        # 1. Transport
        transport_ctx = _make_transport(self.config)
        self._transport_cm = transport_ctx  # 持有到 _disconnect
        read_stream, write_stream = await transport_ctx.__aenter__()

        # 2. Session（必须 enter context manager 才会启动 dispatcher）
        session = ClientSession(read_stream, write_stream)
        self._session_cm = session  # 持有到 _disconnect
        await session.__aenter__()
        self.session = session

        # 3. Handshake + discovery
        await session.initialize()
        result = await session.list_tools()
        self.tools = list(result.tools)

    async def _disconnect(self) -> None:
        """按创建顺序反向清理（先 session，再 transport）。"""
        try:
            if hasattr(self, "_session_cm"):
                await self._session_cm.__aexit__(None, None, None)
                del self._session_cm
            self.session = None
        except Exception:
            pass
        try:
            if hasattr(self, "_transport_cm"):
                await self._transport_cm.__aexit__(None, None, None)
                del self._transport_cm
        except Exception:
            pass

    def stop(self) -> None:
        """请求停止并等待线程退出。"""
        self._stop_event.set()
        # 通过事件循环 schedule 一个任务让 run_forever 退出
        if self.loop and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    asyncio.sleep(0), self.loop
                )
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=5)

    def call_tool_sync(self, tool_name: str, args: dict) -> str:
        """同步调用工具（从主线程调用，桥接到后台事件循环）。"""
        if not self.session or not self.loop or self.loop.is_closed():
            return json.dumps({
                "exit_code": -1,
                "error": f"MCP Server '{self.name}' 未就绪或已断开",
            }, ensure_ascii=False)

        async def _call() -> str:
            try:
                result = await self.session.call_tool(tool_name, arguments=args)
            except Exception as e:
                return json.dumps({
                    "exit_code": -1,
                    "error": f"MCP Server '{self.name}' 调用 {tool_name} 失败: {e}",
                }, ensure_ascii=False)

            # result 是 CallToolResult，有 content 列表和 is_error 标志
            if getattr(result, "is_error", False):
                texts = []
                for item in getattr(result, "content", []):
                    if getattr(item, "type", None) == "text":
                        texts.append(item.text)
                return json.dumps({
                    "exit_code": -1,
                    "error": (texts[0] if texts else f"MCP 工具 {tool_name} 返回错误"),
                }, ensure_ascii=False)

            # 成功 —— 拼接所有 content 文本
            texts = []
            for item in getattr(result, "content", []):
                if getattr(item, "type", None) == "text":
                    texts.append(item.text)
                elif getattr(item, "type", None) == "image":
                    texts.append("[image omitted]")
                elif getattr(item, "type", None) == "audio":
                    texts.append("[audio omitted]")
            body = "\n".join(texts) if texts else "(空响应)"
            return body

        # 跨线程调度
        future = asyncio.run_coroutine_threadsafe(_call(), self.loop)
        try:
            return future.result(timeout=60)
        except Exception as e:
            return json.dumps({
                "exit_code": -1,
                "error": f"MCP 调用超时或异常: {e}",
            }, ensure_ascii=False)


# ========== 便捷入口 ==========

def build_mcp_tool_registry() -> tuple[list[dict], dict[str, Callable[[dict], str]], MCPServerManager]:
    """读取 .mcp.json → 连接所有 servers → 返回 (schema_list, tool_map, manager)。

    没有配置文件或所有 server 都连不上时，返回空集合，不影响本地工具。
    """
    config = load_mcp_config()
    if "__error__" in config:
        print(f"[MCP] 配置错误: {config['__error__']}", file=sys.stderr, flush=True)
        return [], {}, MCPServerManager()

    if not config.get("servers"):
        print("[MCP] 未在当前目录发现 .mcp.json，跳过 MCP 工具加载", file=sys.stderr, flush=True)
        return [], {}, MCPServerManager()

    mgr = MCPServerManager()
    mgr.connect_all(config)
    return mgr.tool_schemas, mgr.tool_map, mgr
