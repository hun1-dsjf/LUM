"""
斜杠命令注册中心。每个命令 = (name, alias1, alias2, ..., handler_fn, description)

handler_fn 签名: async def handler(app: AgentApp, args: str) -> None
args = 用户输入的命令后面的所有文本（已 strip）。

自动补全面板在 TUI 的 Input 里通过输入 "/" 触发。
"""
from __future__ import annotations

from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from ui.tui import AgentApp


SlashHandler = Callable[["AgentApp", str], None]


class SlashCommand:
    """单条斜杠命令定义。"""
    __slots__ = ("names", "handler", "description")

    def __init__(self, names: list[str], handler: SlashHandler, description: str):
        self.names: list[str] = names        # 主名 + 别名，全部小写
        self.handler = handler
        self.description = description

    @property
    def primary(self) -> str:
        return self.names[0]


class SlashRegistry:
    """全局斜杠命令注册表 + 查找。"""

    def __init__(self) -> None:
        self._commands: list[SlashCommand] = []

    def register(self, cmd: SlashCommand) -> None:
        self._commands.append(cmd)

    def all(self) -> list[SlashCommand]:
        return list(self._commands)

    def match(self, text: str) -> tuple[SlashCommand, str] | None:
        """text 已 strip；首字符应该是 '/'。返回 (command, args) 或 None。"""
        if not text.startswith("/"):
            return None
        tokens = text.split(None, 1)  # 切命令名 + 后面全部
        name = tokens[0][1:].lower()  # 去掉前导 '/'
        args = tokens[1] if len(tokens) > 1 else ""
        for cmd in self._commands:
            if name in cmd.names:
                return cmd, args
        return None

    def suggestions(self, prefix: str = "") -> list[tuple[str, str]]:
        """输入框补全面板：prefix 是 '/' 之后已经输入的字符。
        返回 [(name, description), ...]。"""
        parts = prefix.lstrip("/").split(None, 1)
        cmd_prefix = parts[0].lower() if parts else ""
        result = []
        for c in self._commands:
            if not cmd_prefix or any(n.startswith(cmd_prefix) for n in c.names):
                result.append((f"/{c.primary}", c.description))
        return result


# —— 默认命令集 ——

def build_default_registry() -> SlashRegistry:
    """注册所有内置命令。"""
    reg = SlashRegistry()

    # /help —— 列出所有命令
    async def _help(app: "AgentApp", args: str) -> None:
        cmds = reg.all()
        lines = ["## 📖 可用斜杠命令\n"]
        for c in cmds:
            aliases = f" (别名: {', '.join('/' + a for a in c.names[1:])})" if len(c.names) > 1 else ""
            lines.append(f"- `/{c.primary}`{aliases} — {c.description}")
        app._history_log("\n".join(lines), style="cyan")
    reg.register(SlashCommand(["help", "h", "?"], _help, "列出所有斜杠命令"))

    # /quit —— 退出（等同于在输入框输入 quit）
    async def _quit(app: "AgentApp", args: str) -> None:
        app.exit()
    reg.register(SlashCommand(["quit", "exit", "bye", "q"], _quit, "退出程序"))

    # /compact —— 压缩上下文
    async def _compact(app: "AgentApp", args: str) -> None:
        await app._handle_compact()
    reg.register(SlashCommand(["compact", "compress", "c"], _compact, "压缩上下文窗口，生成摘要归档"))

    # /clear —— 清空对话（保留 system，重置会话）
    async def _clear(app: "AgentApp", args: str) -> None:
        await app._handle_clear()
    reg.register(SlashCommand(["clear", "reset"], _clear, "清空对话历史（保留 system，不可恢复）"))

    # /new —— 新建会话（自动保存当前）
    async def _new(app: "AgentApp", args: str) -> None:
        await app._handle_new_session(args.strip())
    reg.register(SlashCommand(["new", "n"], _new, "新建会话（自动保存当前会话）"))

    # /save —— 手动保存当前会话
    async def _save(app: "AgentApp", args: str) -> None:
        await app._handle_save_session(args.strip())
    reg.register(SlashCommand(["save", "s"], _save, "手动保存当前会话到 .agents/sessions/"))

    # /list —— 列出历史会话
    async def _list(app: "AgentApp", args: str) -> None:
        await app._show_sessions_panel("resume" if args == "--resume" else "")
    reg.register(SlashCommand(["list", "ls", "sessions"], _list, "列出所有已保存会话（加 --resume 可直接选择恢复）"))

    # /resume —— 恢复会话
    async def _resume(app: "AgentApp", args: str) -> None:
        await app._handle_resume(args.strip())
    reg.register(SlashCommand(["resume", "load", "r"], _resume, "恢复指定会话 ID；无参数时弹出列表面板"))

    # /delete —— 删除会话
    async def _delete(app: "AgentApp", args: str) -> None:
        await app._show_sessions_panel("delete")
    reg.register(SlashCommand(["delete", "del"], _delete, "删除会话（弹出列表选择）"))

    # /context —— 显示 Token 用量
    async def _context(app: "AgentApp", args: str) -> None:
        if app._agent:
            s = app._agent.context_status()
            app._history_log(
                f"📊 上下文状态: {s['current']:,} / {s['window']:,} tokens "
                f"({s['percent']}%) · {s['messages_count']} 条消息"
                f"{' · 正在压缩' if s['compacting'] else ''}",
                style="magenta",
            )
        else:
            app._history_log("Agent 未初始化", style="yellow")
    reg.register(SlashCommand(["context", "status", "ctx"], _context, "显示当前 Token 用量与窗口占比"))

    # /mcp —— 显示已连接 MCP Server
    async def _mcp(app: "AgentApp", args: str) -> None:
        app._show_mcp_status()
    reg.register(SlashCommand(["mcp", "servers"], _mcp, "显示已连接的 MCP Server 和工具列表"))

    # /model —— 显示 / 切换模型（只读展示，真实切换需要重启）
    async def _model(app: "AgentApp", args: str) -> None:
        cur = app._agent.config.model if app._agent else "?"
        base = app._agent.config.base_url if app._agent else "?"
        if args:
            app._history_log(
                f"⚠️  运行时切换模型暂未支持。当前: {cur} @ {base}。请在 .env 修改 MODEL= 后重启。",
                style="yellow",
            )
        else:
            app._history_log(f"🤖 当前模型: {cur}\n   Base URL: {base}", style="magenta")
    reg.register(SlashCommand(["model"], _model, "显示当前模型（运行时暂不支持切换，请改 .env）"))

    # /system —— 打印当前 system prompt
    async def _system(app: "AgentApp", args: str) -> None:
        if app._agent:
            sys_msg = next((m for m in app._agent.messages if m.get("role") == "system"), None)
            content = (sys_msg or {}).get("content", "(无)") if sys_msg else "(无)"
            app._history_log(f"**System Prompt:**\n{content}", style="dim")
        else:
            app._history_log("Agent 未初始化", style="yellow")
    reg.register(SlashCommand(["system", "sys"], _system, "打印当前 System Prompt"))

    # /skills —— 列出已加载 Skill
    async def _skills(app: "AgentApp", args: str) -> None:
        if app._agent and app._agent.skills:
            lines = [f"## 🧩 已加载 Skills ({len(app._agent.skills)})\n"]
            for sk in app._agent.skills:
                lines.append(f"- `{sk.name}` — {sk.description}")
            app._history_log("\n".join(lines), style="magenta")
        else:
            app._history_log("没有加载任何 Skill", style="yellow")
    reg.register(SlashCommand(["skills", "sk"], _skills, "列出已加载的 Agent Skills"))

    # /banner —— 打一条横幅
    async def _banner(app: "AgentApp", args: str) -> None:
        app._refresh_sidebar()
        app._history_log("🔄 侧边栏已刷新", style="dim")
    reg.register(SlashCommand(["refresh"], _banner, "刷新侧边栏（会话列表 / MCP 状态）"))

    return reg
