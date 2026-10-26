"""
XAgent 入口程序。

启动流程：
  1. 加载 .env → LLMConfig
  2. 创建 Agent 引擎（Core）
  3. 创建 Textual AgentApp（UI，自身实现 EventCallback）
  4. app.init_agent(agent) → app.run()

运行：
  python main.py              # TUI 交互模式
  python main.py --prompt "xxx"   # 单次非交互模式（打印到 stdout）
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 把 XAgent 目录加进 sys.path（从任意位置都能运行）
XAGENT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(XAGENT_ROOT))

from config.settings import LLMConfig
from core.agent import Agent


# ========== CLI 参数 ==========

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


# ========== 单次模式（无 TUI，方便脚本化测试）==========

class StdoutCallback:
    """EventCallback 实现 —— 纯 stdout 输出（用于 --prompt 模式）。"""

    def on_text_delta(self, delta: str) -> None:
        print(delta, end="", flush=True)

    def on_tool_start(self, name: str, args: dict) -> None:
        print(f"\n  [tool] {name}({args}) => ", end="", flush=True)

    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        print(result)

    def on_ai_done(self, full_text: str) -> None:
        print()


async def run_once(prompt: str) -> None:
    config = LLMConfig.from_env()
    agent = Agent(config=config, callback=StdoutCallback())
    await agent.chat(prompt)


# ========== TUI 模式 ==========

def run_tui() -> None:
    from ui.tui import AgentApp

    config = LLMConfig.from_env()
    app = AgentApp()
    app.init_agent(Agent(config=config, callback=app))
    app.run()


# ========== main ==========

def main() -> None:
    args = parse_args()
    if args["prompt"]:
        asyncio.run(run_once(args["prompt"]))
    else:
        run_tui()


if __name__ == "__main__":
    main()
