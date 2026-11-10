"""
XAgent 入口程序。

启动流程：
  1. ensure_config_ini() → 首次运行自动生成模板并提示用户
  2. load_agent_config() + LLMConfig.from_env() → 加载配置
  3. build_full_tools() → 同步连接 MCP + 加载本地工具
  4. TUI: init_agent(agent, mgr=...) → app.run()
  5. mgr.shutdown()

运行：
  python main.py                   # TUI 交互模式
  python main.py --prompt "xxx"    # 单次非交互模式
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

XAGENT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(XAGENT_ROOT))

from config.config_manager import (
    LLMConfig, AGENT_CONFIG, ensure_config_ini, show_first_run_warning,
)
from core.agent import Agent
from tools import build_full_tools


def parse_args() -> dict:
    args = {"prompt": None}
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == "--prompt" and i + 1 < len(sys.argv):
            args["prompt"] = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    return args


class StdoutCallback:
    def on_text_delta(self, delta: str) -> None:
        print(delta, end="", flush=True)
    def on_tool_start(self, name: str, args: dict) -> None:
        print(f"\n  [tool] {name}({args}) => ", end="", flush=True)
    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        print(result)
    def on_ai_done(self, full_text: str) -> None:
        print()
    # 上下文回调（--prompt 模式不需要）
    def on_context_usage(self, c, w, p): pass
    def on_context_warning(self, p): pass
    def on_compaction_start(self): pass
    def on_compaction_done(self, aid): pass
    def on_compaction_failed(self, e): pass


async def run_once(prompt: str) -> None:
    config = LLMConfig.from_env()
    tools_schema, tool_map, _mgr = build_full_tools()
    agent = Agent(config=config, callback=StdoutCallback(),
                  tools_schema=tools_schema, tool_map=tool_map)
    await agent.chat(prompt)


def run_tui() -> None:
    from ui.tui import AgentApp

    config = LLMConfig.from_env()

    # —— Phase 1: 准备阶段（全链路 devnull，防并发写 ScreenStackError）——
    _orig_stdout, _orig_stderr = sys.stdout, sys.stderr
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        tools_schema, tool_map, mgr = build_full_tools()
        agent = Agent(config=config, callback=None,
                      tools_schema=tools_schema, tool_map=tool_map)
        app = AgentApp()
        app.init_agent(agent, mgr=mgr)
    except Exception:
        sys.stdout.close(); sys.stderr.close()
        sys.stdout, sys.stderr = _orig_stdout, _orig_stderr
        raise

    # Phase 2: 恢复，打启动提示（stderr 安全）
    sys.stdout.close(); sys.stderr.close()
    sys.stdout, sys.stderr = _orig_stdout, _orig_stderr

    # 侧边栏异步刷新需要知道 mgr 已完成；这里直接先同步打印一次 mcp 状态
    mcp_names = mgr.server_names
    skills_count = len(agent.skills)
    print(
        f"[XAgent] TUI 启动中… "
        f"MCP: {', '.join(mcp_names) if mcp_names else '无'} · "
        f"Skills: {skills_count} · "
        f"窗口: {agent.window_size // 1024}k · "
        f"按 Esc 或 /quit 退出",
        file=sys.stderr, flush=True,
    )

    # Phase 3: app.run() 全程 devnull
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = open(os.devnull, "w", encoding="utf-8")
    try:
        app.run()
    finally:
        sys.stdout.close(); sys.stderr.close()
        sys.stdout, sys.stderr = _orig_stdout, _orig_stderr
        mgr.shutdown()


def main() -> None:
    # 1. 检查 config.ini 是否首次生成（TUI 模式下我们稍后吞 stdout，所以这里提前提示）
    cfg_path, was_created = ensure_config_ini()

    args = parse_args()

    # 2. --prompt 模式可以直接跑（不检查 API_KEY，让运行时抛）
    if args["prompt"]:
        if was_created:
            show_first_run_warning(cfg_path)
            sys.exit(1)
        asyncio.run(run_once(args["prompt"]))
        return

    # 3. TUI 模式
    if was_created:
        # 模板已生成，用户需要修改后重启
        show_first_run_warning(cfg_path)
        sys.exit(0)

    run_tui()


if __name__ == "__main__":
    main()
