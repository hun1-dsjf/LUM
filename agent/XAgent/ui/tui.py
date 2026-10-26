"""
XAgent Textual TUI 界面。

实现 EventCallback 协议，将 Core 层推送的事件实时渲染到界面。

架构：
  - RichLog #history     → 对话历史（用户消息、工具调用、已完成的 AI 回复）
                            只追加完整的消息，从不流式写入
  - Markdown #live-reply → 当前正在流式生成的 AI 回复
                            on_text_delta 时累积完整文本，.update() 整体刷新
                            Markdown 组件天然支持块级渲染和自动换行
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent

from textual.app import App, ComposeResult
from textual.reactive import reactive
from textual.widgets import Header, Input, RichLog, Markdown


class AgentApp(App):
    """Textual TUI：对话历史区 + Markdown 流式回复区 + 输入框。"""

    TITLE = "XAgent"
    CSS = """
    Screen {
        layout: vertical;
    }

    #history {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        background: $surface;
    }

    #live-reply {
        height: auto;
        max-height: 40%;
        border: round $secondary;
        padding: 0 1;
        background: $surface;
        margin-top: 1;
        display: none;   /* 默认隐藏，流式开始时显示 */
    }

    #live-reply.visible {
        display: block;
    }

    #input {
        dock: bottom;
        margin: 1 0;
    }

    Header {
        background: $primary;
    }
    """

    # —— 响应式状态 ——
    _current_ai_buffer: list[str] = []   # 累积本轮 AI 的完整回复
    _agent: "Agent | None" = None
    _streaming_active: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="history", markup=True, auto_scroll=True, wrap=True)
        yield Markdown(id="live-reply")
        yield Input(placeholder="输入消息（quit / exit / bye 或 Esc 退出）", id="input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    # ========== 输入处理 ==========

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if self._streaming_active:
            return  # 正在流式输出，忽略输入
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text in ("quit", "exit", "bye"):
            self.exit()
            return
        await self._run_agent(text)

    # ========== 历史日志（只追加完整消息）==========

    def _history_log(self, msg: str, style: str | None = None) -> None:
        """向 RichLog 追加一条完整的历史消息。"""
        rl: RichLog = self.query_one("#history")
        if style:
            rl.write(f"[{style}]{msg}[/]")
        else:
            rl.write(msg)

    # ========== 流式 Markdown 回复区 ==========

    def _show_live_reply(self) -> None:
        """显示实时回复区，重置缓冲。"""
        self._current_ai_buffer = []
        self.query_one("#live-reply").add_class("visible")

    def _update_live_reply(self) -> None:
        """用累积的完整文本刷新 Markdown 组件（整体 .update()，不逐字 write）。"""
        full_text = "".join(self._current_ai_buffer)
        self.query_one("#live-reply").update(f"**🤖 AI:** {full_text}")

    def _hide_live_reply(self) -> None:
        """隐藏实时回复区。"""
        self.query_one("#live-reply").remove_class("visible")
        self.query_one("#live-reply").update("")
        self._current_ai_buffer = []

    # ========== EventCallback 实现 ==========

    def on_text_delta(self, delta: str) -> None:
        """流式收到一段文本增量：追加到缓冲 → 整体刷新 Markdown。"""
        self._current_ai_buffer.append(delta)
        self._update_live_reply()

    def on_tool_start(self, name: str, args: dict) -> None:
        self._history_log(f"\n🛠  正在执行 {name}({args})", style="yellow")

    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        self._history_log(f"✅ {name} 执行完毕", style="green")
        short = result if len(result) <= 200 else result[:200] + "..."
        self._history_log(f"   {short}", style="dim")

    def on_ai_done(self, full_text: str) -> None:
        """本轮 AI 回复结束：把完整文本固化到历史区，隐藏实时区。"""
        self._history_log(f"\n🤖 AI: {full_text}", style="magenta")
        self._hide_live_reply()
        self._streaming_active = False
        self.query_one(Input).disabled = False
        self.query_one(Input).focus()

    # ========== Agent 调度 ==========

    async def _run_agent(self, user_input: str) -> None:
        if self._agent is None:
            raise RuntimeError("Agent 未初始化，请先调用 app.init_agent(agent)")

        self._streaming_active = True
        self.query_one(Input).disabled = True

        # 用户消息 → 历史区
        self._history_log(f"\n👤 你: {user_input}", style="cyan")
        # 开启实时回复区
        self._show_live_reply()

        await self._agent.chat(user_input)

    # ========== 生命周期 ==========

    def init_agent(self, agent: "Agent") -> None:
        """注入 Agent 实例（self 作为 EventCallback）。"""
        self._agent = agent
