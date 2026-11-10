"""
XAgent Textual TUI —— 侧边栏 + 主对话区 + 底部状态栏。

布局：
  ┌──── Sidebar (固定宽) ────┬─────────────────────┐
  │  🧩 Sessions             │  🕒 Header            │
  │  📦 MCP Servers          │  💬 对话历史           │
  │  📌 Skills               │  🤖 流式回复区          │
  │                          │  🔧 输入框             │
  │                          │  ⚡ 状态栏             │
  └──────────────────────────┴─────────────────────┘

MCP 加载：异步（先渲染界面，后在后台连接，连接完成后自动刷新 Sidebar 的 MCP 区域）。
ScreenStackError 防护：全部 UI 操作都包 try/except ScreenStackError + is_running 检查。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.agent import Agent
    from core.session_store import SessionStore

from textual.app import App, ComposeResult, ScreenStackError
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header, Input, RichLog, Markdown, Static, ListView, ListItem, OptionList,
)
from textual.screen import Screen
from textual.reactive import reactive

from config.config_manager import AGENT_CONFIG
from core.slash_commands import SlashRegistry, build_default_registry
from core.session_store import SessionStore
from core import agents_md


# =========================================================
# 斜杠命令补全面板（输入 / 时触发）
# =========================================================

class CommandPicker(Screen):
    """居中弹层：列出斜杠命令 + 选不中取消 + Enter 选中执行。"""

    BINDINGS = [("escape", "close", "取消"), ("enter", "confirm", "执行所选命令")]
    CSS = """
    Screen { align: center middle; }
    #cmd-box {
        width: 55%; height: 65%;
        border: round $primary; background: $surface; padding: 1 2;
    }
    #cmd-title { text-align: center; color: $accent; }
    OptionList { height: 1fr; border: round $secondary; }
    #cmd-hint { text-align: center; color: $text-muted; margin-top: 1; }
    """

    def __init__(self, registry: SlashRegistry, prefix: str = ""):
        super().__init__()
        self._registry = registry
        self._prefix = prefix  # 用户已输入的 '/' 之后的字符

    def compose(self) -> ComposeResult:
        title = f"📜 斜杠命令补全（已输入：/{self._prefix}）" if self._prefix else "📜 斜杠命令补全"
        with Vertical(id="cmd-box"):
            yield Static(title, id="cmd-title")
            suggestions = self._registry.suggestions(self._prefix)
            if not suggestions:
                yield Static(f"（没有匹配 '/{self._prefix}' 的命令，按 Esc 取消）")
            else:
                ol = OptionList(id="cmd-list")
                for name, desc in suggestions:
                    ol.add_option(f"{name:10s}  {desc}")
                yield ol
            yield Static("↑↓ 导航 · Enter 执行 · Esc 取消", id="cmd-hint")

    def on_mount(self) -> None:
        # 延迟一帧再 focus（push_screen 刚回来时 Textual 内部可能还在切换焦点）
        self.set_interval(0.02, self._focus_list, repeat=False)

    def _focus_list(self) -> None:
        try:
            ol = self.query_one("#cmd-list", OptionList)
            ol.focus()
            self.set_focus(ol)
        except Exception:
            pass

    def on_key(self, event) -> None:
        """重保险：把 up/down/enter 手动派发给 OptionList（即使焦点没在它身上）。"""
        key = getattr(event, "key", "")
        if key in ("up", "down", "enter"):
            try:
                ol = self.query_one("#cmd-list", OptionList)
                # 给 OptionList 派发一个按键事件
                ol.on_key(event)
                event.stop()
                event.prevent_default()
            except Exception:
                pass

    def action_close(self) -> None:
        self.dismiss(result=None)

    def action_confirm(self) -> None:
        ol = self.query_one("#cmd-list", OptionList)
        if ol.option_count == 0:
            self.action_close()
            return
        idx = ol.highlighted or 0
        if 0 <= idx < ol.option_count:
            text = ol.get_option_at_index(idx).prompt
            name = text.split(None, 1)[0] if text else ""
            self.dismiss(result=name)

    def on_option_list_option_selected(self, event) -> None:
        self.action_confirm()


# =========================================================
# 会话选择弹窗（/resume /delete /list --resume 触发）
# =========================================================

class SessionPicker(Screen):
    """居中弹层：会话列表 + 上下导航 + 回车选中 + ESC 取消。"""

    BINDINGS = [("escape", "close", "取消"), ("enter", "confirm", "选择")]
    CSS = """
    Screen {
        align: center middle;
    }
    #picker-box {
        width: 70%;
        height: 70%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #picker-title {
        text-align: center;
        color: $accent;
    }
    ListView {
        height: 1fr;
        border: round $secondary;
    }
    #picker-hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    def __init__(self, mode: str = "resume"):
        super().__init__()
        self.mode = mode  # "resume" | "delete"
        self.selected_id: str | None = None

    def compose(self) -> ComposeResult:
        title_text = "选择会话恢复" if self.mode == "resume" else "选择会话删除"
        with Vertical(id="picker-box"):
            yield Static(f"📂 {title_text}", id="picker-title")
            sessions = SessionStore.list()
            if not sessions:
                yield Static("（没有任何已保存会话）", id="picker-empty")
                yield Static("按 Esc 取消", id="picker-hint")
                return
            items = [
                ListItem(
                    f"🗓  {s.get('id', '?')}  📝 {s.get('title', '(untitled)')}  💬 {s.get('messages_count', '?')} 条消息  ⏱  {s.get('updated', '?')}",
                    id=s.get("id", "?"),
                )
                for s in sessions
            ]
            yield ListView(*items, id="picker-list")
            hint = "↑↓ 导航 · Enter 选择 · Esc 取消"
            if self.mode == "delete":
                hint += "（删除后不可恢复）"
            yield Static(hint, id="picker-hint")

    def on_mount(self) -> None:
        self.set_interval(0.02, self._focus_list, repeat=False)

    def _focus_list(self) -> None:
        try:
            lv = self.query_one("#picker-list", ListView)
            lv.focus()
            self.set_focus(lv)
        except Exception:
            pass

    def on_key(self, event) -> None:
        """重保险：把 up/down/enter 手动派发给 ListView。"""
        key = getattr(event, "key", "")
        if key in ("up", "down", "enter"):
            try:
                lv = self.query_one("#picker-list", ListView)
                lv.on_key(event)
                event.stop()
                event.prevent_default()
            except Exception:
                pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.selected_id = event.item.id
        self.dismiss(result=self.selected_id)

    def action_close(self) -> None:
        self.dismiss(result=None)

    def action_confirm(self) -> None:
        lv = self.query_one("#picker-list", ListView)
        items = lv.children
        if not items:
            self.action_close()
            return
        idx = lv.index or 0
        if 0 <= idx < len(items):
            self.selected_id = items[idx].id
            self.dismiss(result=self.selected_id)


# =========================================================
# TUI 主 App
# =========================================================

class AgentApp(App):
    TITLE = "XAgent"

    CSS = f"""
    Screen {{
        layout: horizontal;
    }}

    #sidebar {{
        width: {AGENT_CONFIG.sidebar_width};
        height: 100%;
        border: round $primary;
        background: $surface;
        padding: 0 1;
        margin: 0 1 0 0;
    }}

    #sidebar-title {{
        text-align: center;
        color: $accent;
        text-style: bold;
        padding-bottom: 1;
        border-bottom: solid $primary;
    }}

    #sidebar-section-title {{
        color: $text-muted;
        text-style: bold;
        margin-top: 1;
    }}

    #sidebar-content {{
        height: auto;
        margin-bottom: 1;
    }}

    #main-col {{
        width: 1fr;
        height: 100%;
        layout: vertical;
    }}

    #history {{
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        background: $surface;
    }}

    #live-reply {{
        height: auto;
        max-height: 30%;
        border: round $secondary;
        padding: 0 1;
        background: $surface;
        margin-top: 1;
        display: none;
    }}
    #live-reply.visible {{
        display: block;
    }}

    #input {{
        dock: bottom;
        margin: 1 0 0 0;
    }}

    #statusbar {{
        dock: bottom;
        height: auto;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
        border-top: solid $primary;
    }}
    #statusbar.warning {{ color: $warning; }}
    #statusbar.danger  {{ color: $error; }}

    Header {{ background: $primary; }}
    """

    # —— 状态 ——
    _current_ai_buffer: list[str] = []
    _agent: "Agent | None" = None
    _streaming_active: bool = False
    _compacting: bool = False
    _slash_registry: SlashRegistry | None = None
    _current_sid: str | None = None  # 当前会话 ID（首次 /save 后赋值）
    _mgr = None                       # MCP manager（由 init_agent 注入）

    # ========== ScreenStackError 全局防护 ==========

    def clear_selection(self) -> None:
        try:
            super().clear_selection()
        except ScreenStackError:
            pass

    # ========== 组件组装 ==========

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("🧩 XAgent", id="sidebar-title")
                yield Static("📂 Sessions", id="sidebar-section-title-sessions")
                yield Static("(等待加载...)", id="sidebar-sessions")
                yield Static("📦 MCP Servers", id="sidebar-section-title-mcp")
                yield Static("⏳ 加载中...", id="sidebar-mcp")
                yield Static("🧩 Skills", id="sidebar-section-title-skills")
                yield Static("(等待加载...)", id="sidebar-skills")
            with Vertical(id="main-col"):
                yield RichLog(id="history", markup=True,
                              auto_scroll=AGENT_CONFIG.tui_auto_scroll, wrap=True)
                yield Markdown(id="live-reply")
        yield Static("上下文: -- / -- (--%) | MCP: 加载中...", id="statusbar")
        yield Input(
            placeholder=(
                "输入消息（/help 看命令 · /compact 压缩 · /new /resume /save 管理会话 · quit 退出）"
            ),
            id="input",
        )

    def on_mount(self) -> None:
        self._slash_registry = build_default_registry()
        # 立即刷新侧边栏同步内容（Sessions / Skills 已同步可用）
        self._refresh_sidebar_sync()
        # 异步刷新 MCP 区域（等 build_full_tools 完成后动态注入的 manager）
        asyncio.get_event_loop().create_task(self._async_refresh_mcp_when_ready())
        try:
            self.query_one(Input).focus()
        except ScreenStackError:
            pass
        except Exception:
            pass

    async def _async_refresh_mcp_when_ready(self) -> None:
        """等 init_agent 注入 _mgr 后再刷新 MCP 区域（最多等 15 秒）。"""
        for _ in range(30):
            await asyncio.sleep(0.5)
            if self._mgr is not None:
                self._refresh_sidebar_mcp()
                return
        # 超时
        self._sidebar_set("mcp", "（MCP 未连接）")
        self._update_statusbar(
            self.query_one("#statusbar").renderable.plain
            if False else "上下文: -- / -- (--%) | MCP: 未连接",
        )

    # ========== 侧边栏刷新 ==========

    def _sidebar_set(self, section: str, text: str) -> None:
        try:
            wid = self.query_one(f"#sidebar-{section}", Static)
            wid.update(text)
        except (ScreenStackError, Exception):
            pass

    def _refresh_sidebar_sync(self) -> None:
        """刷新同步可获取的区域：Sessions / Skills。"""
        # Sessions
        sessions = SessionStore.list()
        if sessions:
            lines = []
            for s in sessions[:6]:  # 最多 6 条
                mark = "●" if s.get("id") == self._current_sid else " "
                lines.append(f"{mark} {s.get('id', '?')[:10]} {s.get('title', '(untitled)')[:18]}")
            self._sidebar_set("sessions", "\n".join(lines))
        else:
            self._sidebar_set("sessions", "(暂无会话，用 /save 保存)")

        # Skills
        if self._agent and self._agent.skills:
            lines = [f"• {sk.name}" for sk in self._agent.skills]
            self._sidebar_set("skills", "\n".join(lines))
        else:
            self._sidebar_set("skills", "(加载中...)")

    def _refresh_sidebar_mcp(self) -> None:
        if not self._mgr:
            self._sidebar_set("mcp", "(未连接)")
            return
        names = self._mgr.server_names
        if not names:
            self._sidebar_set("mcp", "(无配置)")
            self._update_statusbar(
                self.query_one("#statusbar").renderable.plain
                if False else "上下文: -- / -- (--%) | MCP: 无配置",
            )
            return
        lines = []
        for sname in names:
            lines.append(f"✓ {sname}")
        lines.append("")
        lines.append(f"共 {len(self._mgr.tool_map)} 个工具")
        self._sidebar_set("mcp", "\n".join(lines))
        # 状态栏 MCP 部分
        mcp_part = f"MCP: {', '.join(names)}" if names else "MCP: 无"
        try:
            sb_text = self.query_one("#statusbar").renderable.plain
            # 替换最后一段 MCP: ...
            sb_text = sb_text.rsplit("|", 1)[0] + f"| {mcp_part}"
        except Exception:
            sb_text = f"上下文: -- / -- (--%) | {mcp_part}"
        self._update_statusbar(sb_text)

    def _refresh_sidebar(self) -> None:
        """完整刷新（含同步 + MCP）。"""
        self._refresh_sidebar_sync()
        self._refresh_sidebar_mcp()

    # ========== 斜杠命令拦截 ==========

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.is_running:
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        # —— 斜杠命令优先 ——
        if text.startswith("/") and self._slash_registry:
            hit = self._slash_registry.match(text)
            if hit:
                cmd, args = hit
                try:
                    await cmd.handler(self, args)
                except Exception as e:
                    self._history_log(f"❌ 命令 /{cmd.primary} 执行出错: {e}", style="red")
                return
            else:
                # 未知斜杠输入 → 视为补全触发，弹 CommandPicker
                # 前提：输入不是纯 '/xxx' 带参数（那种真不知道要干啥才弹）
                await self._show_command_picker(text)
                return

        # —— 全局退出关键词 ——
        if text in ("quit", "exit", "bye"):
            self.exit()
            return

        # —— 忙碌检查 ——
        if self._streaming_active or self._compacting:
            self._history_log("⚠️  正在处理上一条请求，请稍候...", style="yellow")
            return

        await self._run_agent(text)

    async def _show_command_picker(self, user_input: str) -> None:
        """弹斜杠命令补全面板；选中则执行；Esc 取消。"""
        if self._slash_registry is None:
            return
        prefix = user_input.lstrip("/").split(None, 1)[0] if len(user_input) > 1 else ""
        picker = CommandPicker(self._slash_registry, prefix=prefix)

        # 禁用主界面 Input，防止它吞掉弹层键盘事件
        input_disabled_backup = False
        try:
            inp = self.query_one(Input)
            input_disabled_backup = inp.disabled
            inp.disabled = True
        except Exception:
            pass

        try:
            worker = self.run_worker(self.push_screen_wait(picker))
            result = await worker.wait()
        except Exception:
            result = None
        finally:
            # 恢复 Input
            try:
                inp = self.query_one(Input)
                inp.disabled = input_disabled_backup
                inp.focus()
            except Exception:
                pass

        if not result:
            if user_input.strip() == "/":
                self._history_log("💡 可用 /help 查看全部斜杠命令", style="dim")
            return
        cmd_hit = self._slash_registry.match(result)
        if cmd_hit:
            cmd, args = cmd_hit
            try:
                await cmd.handler(self, args)
            except Exception as e:
                self._history_log(f"❌ 命令 /{cmd.primary} 执行出错: {e}", style="red")

    # ========== 状态栏 ==========

    def _update_statusbar(self, text: str, level: str = "") -> None:
        if not self.is_running:
            return
        try:
            sb = self.query_one("#statusbar", Static)
            sb.update(text)
            sb.remove_class("warning")
            sb.remove_class("danger")
            if level == "warning":
                sb.add_class("warning")
            elif level == "danger":
                sb.add_class("danger")
        except (ScreenStackError, Exception):
            pass

    # ========== 历史日志 ==========

    def _history_log(self, msg: str, style: str | None = None) -> None:
        if not self.is_running:
            return
        try:
            rl = self.query_one("#history", RichLog)
            if style:
                rl.write(f"[{style}]{msg}[/]")
            else:
                rl.write(msg)
        except (ScreenStackError, Exception):
            pass

    # ========== 流式回复 ==========

    def _show_live_reply(self) -> None:
        if not self.is_running:
            return
        self._current_ai_buffer = []
        try:
            self.query_one("#live-reply").add_class("visible")
        except Exception:
            pass

    def _update_live_reply(self) -> None:
        if not self.is_running:
            return
        try:
            self.query_one("#live-reply").update(
                f"**🤖 AI:** {''.join(self._current_ai_buffer)}"
            )
        except Exception:
            pass

    def _hide_live_reply(self) -> None:
        if not self.is_running:
            return
        try:
            self.query_one("#live-reply").remove_class("visible")
            self.query_one("#live-reply").update("")
        except Exception:
            pass
        self._current_ai_buffer = []

    # ========== EventCallback ==========

    def on_text_delta(self, delta: str) -> None:
        if not self.is_running:
            return
        self._current_ai_buffer.append(delta)
        self._update_live_reply()

    def on_tool_start(self, name: str, args: dict) -> None:
        self._history_log(f"\n🛠  正在执行 {name}({args})", style="yellow")

    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        self._history_log(f"✅ {name} 执行完毕", style="green")
        short = result if len(result) <= 200 else result[:200] + "..."
        self._history_log(f"   {short}", style="dim")

    def on_ai_done(self, full_text: str) -> None:
        self._history_log(f"\n🤖 AI: {full_text}", style="magenta")
        self._hide_live_reply()
        self._streaming_active = False
        self._auto_save_if_needed()
        if not self.is_running:
            return
        try:
            inp = self.query_one(Input)
            inp.disabled = False
            inp.focus()
        except Exception:
            pass

    # ---------- 上下文回调 ----------

    def on_context_usage(self, current: int, window: int, percent: float) -> None:
        if not self.is_running or self._compacting:
            return
        cur_k, win_k = current // 1024, window // 1024
        level = ""
        if percent >= 90:
            level = "danger"
        elif percent >= 80:
            level = "warning"
        mcp_part = "MCP: 连接中"
        if self._mgr:
            names = self._mgr.server_names
            mcp_part = f"MCP: {', '.join(names)}" if names else "MCP: 无"
        self._update_statusbar(
            f"上下文: {cur_k}k / {win_k}k ({percent:.1f}%) | {mcp_part}",
            level=level,
        )

    def on_context_warning(self, percent: float) -> None:
        if not self.is_running or self._compacting:
            return
        if percent >= 90:
            self._history_log(
                f"🚨  上下文 {percent:.0f}%！建议 /compact 压缩", style="red",
            )
        elif percent >= 80:
            self._history_log(
                f"⚠️  上下文 {percent:.0f}%，考虑执行 /compact", style="yellow",
            )

    # ========== 斜杠命令实现（被 SlashRegistry 调用）==========

    # —— /compact ——
    async def _handle_compact(self) -> None:
        if self._compacting:
            self._history_log("⚠️  已在压缩...", style="yellow"); return
        if self._agent is None:
            self._history_log("❌ Agent 未初始化", style="red"); return

        self._compacting = True
        self._history_log("\n🔧  开始压缩上下文...", style="magenta")
        try:
            self.query_one(Input).disabled = True
        except Exception:
            pass

        try:
            archive_id = await self._agent.trigger_compaction()
            self._history_log(f"✅ 压缩完成，归档 {archive_id}", style="green")
            status = self._agent.context_status()
            self._update_statusbar(
                f"上下文: {status['current']} / {status['window']} ({status['percent']}%) | 压缩后",
            )
            # 压缩后触发自动保存（生成新的 compact 后会话）
            await self._handle_save_session("")
        except Exception as e:
            self._history_log(f"❌ 压缩失败（原上下文保留）: {e}", style="red")
        finally:
            self._compacting = False
            try:
                inp = self.query_one(Input); inp.disabled = False; inp.focus()
            except Exception:
                pass

    # —— /clear ——
    async def _handle_clear(self) -> None:
        if self._agent is None:
            self._history_log("❌ Agent 未初始化", style="red"); return
        # 保存当前会话（以防丢失）
        if self._current_sid or len(self._agent.messages) > 1:
            await self._handle_save_session("(clear 前自动保存)")
        # 重建 messages
        system_prompt = next((m for m in self._agent.messages if m.get("role") == "system"), None)
        self._agent.messages = [system_prompt] if system_prompt else []
        self._current_sid = None
        # 重新注入 AGENTS.md
        if AGENT_CONFIG.load_agents_md:
            path = agents_md.maybe_inject_agents_md(
                self._agent.messages, os.getcwd(),
            )
            if path:
                self._history_log(f"📎 重新注入 AGENTS.md ({path})", style="dim")
        self._refresh_sidebar()
        self._history_log("🗑  对话已清空（system prompt 已保留）", style="magenta")

    # —— /new ——
    async def _handle_new_session(self, title: str) -> None:
        if self._agent is None:
            self._history_log("❌ Agent 未初始化", style="red"); return
        # 先保存当前
        if self._current_sid or len(self._agent.messages) > 1:
            await self._handle_save_session("")
        # 构造新会话
        system_prompt = next((m for m in self._agent.messages if m.get("role") == "system"), None)
        self._agent.messages = [system_prompt] if system_prompt else []
        self._current_sid = None
        # 注入 AGENTS.md
        if AGENT_CONFIG.load_agents_md:
            path = agents_md.maybe_inject_agents_md(
                self._agent.messages, os.getcwd(),
            )
            if path:
                self._history_log(f"📎 注入 AGENTS.md ({path})", style="dim")
        # 自动保存为新 ID
        self._current_sid = SessionStore.new_session_id()
        SessionStore.save(self._current_sid, self._agent.messages, title=title or "新会话")
        self._refresh_sidebar()
        self._history_log(
            f"🆕 已创建新会话 {self._current_sid}"
            f"{'（AGENTS.md 已注入）' if AGENT_CONFIG.load_agents_md else ''}",
            style="magenta",
        )

    # —— /save ——
    async def _handle_save_session(self, title: str) -> None:
        if self._agent is None:
            self._history_log("❌ Agent 未初始化", style="red"); return
        if not self._current_sid:
            self._current_sid = SessionStore.new_session_id()
        SessionStore.save(self._current_sid, self._agent.messages, title=title)
        self._refresh_sidebar()
        self._history_log(f"💾 会话已保存 → .agents/sessions/{self._current_sid}.jsonl", style="green")

    def _auto_save_if_needed(self) -> None:
        """每轮 AI 回复后自动保存（失败不阻塞）。"""
        if self._agent is None:
            return
        try:
            if not self._current_sid:
                self._current_sid = SessionStore.new_session_id()
            SessionStore.save(self._current_sid, self._agent.messages)
        except Exception:
            pass

    # —— /resume ——
    async def _handle_resume(self, sid: str) -> None:
        if self._agent is None:
            self._history_log("❌ Agent 未初始化", style="red"); return
        if not sid:
            self._show_sessions_panel("resume")
            return
        msgs = SessionStore.load(sid)
        if msgs is None:
            self._history_log(f"❌ 会话 {sid} 不存在", style="red"); return
        # 先保存当前
        if self._current_sid or len(self._agent.messages) > 1:
            await self._handle_save_session("")
        self._agent.messages = msgs
        self._current_sid = sid
        self._refresh_sidebar()
        self._history_log(f"📂 已恢复会话 {sid}（{len(msgs)} 条消息）", style="green")

    # —— 列表面板 ——
    async def _show_sessions_panel(self, mode: str = "resume") -> None:
        if not self._agent:
            self._history_log("❌ Agent 未初始化", style="red"); return
        picker = SessionPicker(mode=mode)

        # 禁用主界面 Input，防止它吞掉弹层键盘事件
        input_disabled_backup = False
        try:
            inp = self.query_one(Input)
            input_disabled_backup = inp.disabled
            inp.disabled = True
        except Exception:
            pass

        try:
            worker = self.run_worker(self.push_screen_wait(picker))
            sid = await worker.wait()
        except Exception as e:
            self._history_log(f"⚠️  打开会话面板时出错: {e}", style="yellow")
            sid = None
        finally:
            # 恢复 Input
            try:
                inp = self.query_one(Input)
                inp.disabled = input_disabled_backup
                inp.focus()
            except Exception:
                pass

        if not sid:
            self._history_log("（已取消）", style="dim"); return

        if mode == "delete":
            ok = SessionStore.delete(sid)
            if ok:
                self._history_log(f"🗑  已删除会话 {sid}", style="yellow")
                if sid == self._current_sid:
                    self._current_sid = None
            else:
                self._history_log(f"❌ 删除失败 {sid}", style="red")
        elif mode == "resume":
            await self._handle_resume(sid)
        self._refresh_sidebar()

    def _show_mcp_status(self) -> None:
        if not self._mgr:
            self._history_log("MCP 还没加载，请稍后再试", style="yellow"); return
        names = self._mgr.server_names
        if not names:
            self._history_log("没有连接任何 MCP Server（检查 .mcp.json）", style="yellow"); return
        lines = [f"## 📦 MCP 状态（共 {len(names)} 个 Server，{len(self._mgr.tool_map)} 个工具）\n"]
        for sname in names:
            lines.append(f"### ✓ {sname}")
            server_tools = [n for n in self._mgr.tool_map if n.startswith(sname.replace("-", "_"))]
            if not server_tools:
                server_tools = [n for n in self._mgr.tool_map]
            for t in server_tools:
                lines.append(f"  - `{t}`")
        self._history_log("\n".join(lines), style="magenta")

    # ========== Agent 调度 ==========

    async def _run_agent(self, user_input: str) -> None:
        if self._agent is None:
            raise RuntimeError("Agent 未初始化")
        # —— 首次 chat 前注入 AGENTS.md（一次注入，全程复用）——
        if AGENT_CONFIG.load_agents_md:
            path = agents_md.maybe_inject_agents_md(
                self._agent.messages, os.getcwd(),
            )
            if path:
                self._history_log(f"📎 注入 AGENTS.md ({path})", style="dim")

        self._streaming_active = True
        try:
            self.query_one(Input).disabled = True
        except Exception:
            pass
        self._history_log(f"\n👤 你: {user_input}", style="cyan")
        self._show_live_reply()
        try:
            await self._agent.chat(user_input)
        except Exception as e:
            self._hide_live_reply()
            self._streaming_active = False
            self._history_log(f"❌ Agent 执行出错: {e}", style="red")
            try:
                inp = self.query_one(Input); inp.disabled = False; inp.focus()
            except Exception:
                pass

    # ========== 生命周期 ==========

    def init_agent(self, agent: "Agent", mgr=None) -> None:
        self._agent = agent
        agent.callback = self
        # 可选：注入 MCP manager 引用（用于侧边栏异步刷新）
        if mgr is not None:
            self._mgr = mgr
        # 同时也可以把 session_store / slash_registry 等挂上去
