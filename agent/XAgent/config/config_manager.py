"""
XAgent 统一配置管理器。

读取优先级：
  1. <XAgent根>/.env —— API_KEY / BASE_URL / MODEL（敏感信息，不上 .ini）
  2. <XAgent根>/config.ini —— 通用配置；不存在时自动生成模板并提示用户修改
  3. 默认值兜底

硬编码参数已全部迁移至此：window_size / sandbox_root / system_prompt /
compact_temperature / search_top_k / mcp_timeout / ...

config.ini 各 section 参见 CONFIG_TEMPLATE 常量。
"""
from __future__ import annotations

import configparser
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


# =========================================================
# config.ini 模板（不存在时自动生成）
# =========================================================
CONFIG_TEMPLATE = """\
; ============================================================
; XAgent 配置文件 —— 请根据你的环境修改后重启程序
; 敏感信息（API Key）请放在 .env 里，不要放这里
; ============================================================

[llm]
; 模型上下文窗口上限（tokens）。常见值：8192 / 16384 / 32768 / 128000
window_size = 131072

; 压缩时调用 LLM 的温度（0.0 最稳定，0.7 更有创意）
compact_temperature = 0.1

[agent]
; 文件操作沙箱根目录（绝对路径或相对；相对时以 XAgent 目录为基准）
; 留空 = XAgent 目录本身
sandbox_root =

; 是否加载 AGENTS.md（项目根的规则文件），首次注入会话
load_agents_md = true

; AGENTS.md 注入时的最大字符数（超出则截断，避免占满上下文）
agents_md_max_chars = 12000

; 单次 loadSkill 读取内容的最大字符数（超出则截断）
skill_max_chars = 20000

; 单轮对话允许的最大「LLM 调用 + 工具执行」步数，防止无限循环
max_steps = 20

; 单轮对话总超时（秒），超时后停止本轮
turn_timeout = 300

; 是否把工具调用/错误写入 .agents/logs/*.jsonl 结构化追踪日志
trace_enabled = true

; 追踪日志目录（相对 XAgent 根）
trace_dir = .agents/logs

; Skill 目录（相对 XAgent 根）
skills_dir = .agents/skills

; 会话归档目录（相对 XAgent 根）
context_dir = .agents/context

; 会话持久化目录（相对 XAgent 根）
sessions_dir = .agents/sessions

[mcp]
; MCP 连接/启动超时（秒），所有 Server 并行连接，共享该超时窗口
timeout = 10

[search]
; 百度千帆搜索 API（可选；留空则 searchWeb 返回“未配置”错误）
baidu_qianfan_api_key =
qianfan_endpoint = https://qianfan.baidubce.com/v2/ai_search/web_search
search_top_k = 10
search_edition = standard

[tui]
; 侧边栏宽度（字符）
sidebar_width = 30

; 字体主题：auto / light / dark
theme = auto

; 自动滚动历史窗口
auto_scroll = true
"""


# =========================================================
# 路径定位
# =========================================================

def _xagent_root() -> str:
    if getattr(sys, "frozen", False):
        mp = getattr(sys, "_MEIPASS", None)
        if mp and os.path.isdir(mp):
            return mp
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _work_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


XAGENT_ROOT = _xagent_root()
WORK_ROOT = _work_root()

# 加载 .env
load_dotenv(os.path.join(XAGENT_ROOT, ".env"))


# =========================================================
# config.ini 自动生成
# =========================================================

def ensure_config_ini() -> tuple[str, bool]:
    """确保 config.ini 存在且包含所有必需 section。
    不存在 → 写入完整模板；存在但 section 缺失 → 追加缺失 section（保留用户已有配置）。
    返回 (path, was_missing_or_upgraded)。
    """
    path = os.path.join(XAGENT_ROOT, "config.ini")
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(CONFIG_TEMPLATE)
        return path, True

    # 检查是否需要升级（缺失 [agent] section 视为旧模板）
    ini = configparser.ConfigParser()
    ini.read(path, encoding="utf-8-sig")
    needed = ("llm", "agent", "mcp", "tui")
    missing = [s for s in needed if not ini.has_section(s)]
    if not missing:
        return path, False

    # 追加缺失 section（用 CONFIG_TEMPLATE 里的对应 section 作为模板）
    upgraded = False
    template_ini = configparser.ConfigParser()
    template_ini.read_string(CONFIG_TEMPLATE)
    with open(path, "a", encoding="utf-8") as f:
        for sec in missing:
            f.write(f"\n[{sec}]\n")
            for key, val in template_ini.items(sec):
                f.write(f"{key} = {val}\n")
            upgraded = True
    return path, upgraded


# =========================================================
# 强类型配置
# =========================================================

@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = os.getenv("API_KEY", "").strip()
        return cls(
            api_key=api_key,
            base_url=os.getenv("BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.getenv("MODEL", "deepseek-chat"),
        )


@dataclass(frozen=True)
class AgentConfig:
    """Agent 运行时的全部可调参数（从 config.ini 读取 + 默认值）。"""
    window_size: int = 128 * 1024
    compact_temperature: float = 0.1
    sandbox_root: str = ""
    load_agents_md: bool = True
    agents_md_max_chars: int = 12000
    skill_max_chars: int = 20000
    max_steps: int = 20
    turn_timeout: int = 300
    trace_enabled: bool = True
    trace_dir: str = ".agents/logs"
    skills_dir: str = ".agents/skills"
    context_dir: str = ".agents/context"
    sessions_dir: str = ".agents/sessions"
    mcp_timeout: int = 10
    search_top_k: int = 10
    search_edition: str = "standard"
    qianfan_endpoint: str = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    qianfan_api_key: str = ""
    sidebar_width: int = 30
    tui_theme: str = "auto"
    tui_auto_scroll: bool = True

    @property
    def sandbox_root_abs(self) -> str:
        if self.sandbox_root:
            p = Path(self.sandbox_root)
            if p.is_absolute():
                return str(p)
            return str((Path(WORK_ROOT) / p).resolve())
        return WORK_ROOT

    @property
    def skills_dir_abs(self) -> str:
        return str((Path(WORK_ROOT) / self.skills_dir).resolve())

    @property
    def context_dir_abs(self) -> str:
        return str((Path(WORK_ROOT) / self.context_dir).resolve())

    @property
    def sessions_dir_abs(self) -> str:
        return str((Path(WORK_ROOT) / self.sessions_dir).resolve())

    @property
    def trace_dir_abs(self) -> str:
        return str((Path(WORK_ROOT) / self.trace_dir).resolve())


def load_agent_config() -> AgentConfig:
    """从 config.ini 构建 AgentConfig；缺失的 section/key 全部用默认值兜底。"""
    path, _ = ensure_config_ini()
    ini = configparser.ConfigParser()
    ini.read(path, encoding="utf-8-sig")

    def _gsec(sec: str) -> configparser.SectionProxy:
        if not ini.has_section(sec):
            ini.add_section(sec)
        return ini[sec]

    llm_s = _gsec("llm")
    agent_s = _gsec("agent")
    mcp_s = _gsec("mcp")
    search_s = _gsec("search")
    tui_s = _gsec("tui")

    return AgentConfig(
        window_size=llm_s.getint("window_size", fallback=128 * 1024),
        compact_temperature=llm_s.getfloat("compact_temperature", fallback=0.1),
        sandbox_root=agent_s.get("sandbox_root", fallback="").strip(),
        load_agents_md=agent_s.getboolean("load_agents_md", fallback=True),
        agents_md_max_chars=agent_s.getint("agents_md_max_chars", fallback=12000),
        skill_max_chars=agent_s.getint("skill_max_chars", fallback=20000),
        max_steps=agent_s.getint("max_steps", fallback=20),
        turn_timeout=agent_s.getint("turn_timeout", fallback=300),
        trace_enabled=agent_s.getboolean("trace_enabled", fallback=True),
        trace_dir=agent_s.get("trace_dir", fallback=".agents/logs").strip() or ".agents/logs",
        skills_dir=agent_s.get("skills_dir", fallback=".agents/skills").strip() or ".agents/skills",
        context_dir=agent_s.get("context_dir", fallback=".agents/context").strip() or ".agents/context",
        sessions_dir=agent_s.get("sessions_dir", fallback=".agents/sessions").strip() or ".agents/sessions",
        mcp_timeout=mcp_s.getint("timeout", fallback=10),
        qianfan_api_key=search_s.get("baidu_qianfan_api_key", fallback="").strip(),
        qianfan_endpoint=search_s.get("qianfan_endpoint",
                                       fallback="https://qianfan.baidubce.com/v2/ai_search/web_search").strip(),
        search_top_k=search_s.getint("search_top_k", fallback=10),
        search_edition=search_s.get("search_edition", fallback="standard").strip(),
        sidebar_width=tui_s.getint("sidebar_width", fallback=30),
        tui_theme=tui_s.get("theme", fallback="auto").strip() or "auto",
        tui_auto_scroll=tui_s.getboolean("auto_scroll", fallback=True),
    )


def show_first_run_warning(path: str) -> None:
    """首次运行提示（stdout）。"""
    print()
    print("=" * 60)
    print("  ⚠️  首次运行 XAgent")
    print("=" * 60)
    print()
    print(f"  已为您生成配置模板：{path}")
    print()
    print("  请完成以下操作后重新启动：")
    print()
    print("  1. 在同目录下创建 .env 文件，填入 API 密钥：")
    print("       API_KEY=sk-xxxxxxxxxxxxxxxx")
    print("       BASE_URL=https://api.deepseek.com     (可选，默认 DeepSeek)")
    print("       MODEL=deepseek-chat                   (可选)")
    print()
    print("  2.（可选）编辑 config.ini 调整窗口大小、沙箱根等。")
    print()
    print("  3. 重新运行  python main.py")
    print()
    print("=" * 60)


# 模块加载时就检查一次（TUI 模式下我们吞掉 stdout/stderr，所以 main.py 里会单独检查）
_CONFIG_PATH, _WAS_CREATED = ensure_config_ini()
AGENT_CONFIG = load_agent_config()
SANDBOX_ROOT = AGENT_CONFIG.sandbox_root_abs
