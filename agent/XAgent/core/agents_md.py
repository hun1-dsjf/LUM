"""
AGENTS.md 注入 —— "一次注入，全程复用"。

首次 chat() 前检查项目根是否存在 AGENTS.md，若有且 messages 里还没注入过，
追加一条 user message，带上 AGENTS.md 原文。后续 chat() 复用已注入的消息，
不重复追加，确保上下文缓存有效性。
"""
from __future__ import annotations

import os
from pathlib import Path

from config.config_manager import AGENT_CONFIG


_AGENTS_MD_MARKER = "<!-- XAgent injected AGENTS.md -->"


def _find_agents_md(start_dir: str) -> str | None:
    """向上查找 AGENTS.md / AGENT.md（最多 10 层）。找到返回绝对路径，否则 None。"""
    cursor = Path(start_dir).resolve()
    for _ in range(10):
        for filename in ("AGENTS.md", "AGENT.md"):
            candidate = cursor / filename
            if candidate.is_file():
                return str(candidate.resolve())
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return None


def has_injected_agents_md(messages: list[dict]) -> bool:
    """检查 messages 里是否已有 AGENTS.md 注入的 user message。"""
    for m in messages:
        if m.get("role") == "user":
            content = m.get("content") or ""
            if isinstance(content, str) and _AGENTS_MD_MARKER in content:
                return True
    return False


def maybe_inject_agents_md(messages: list[dict], project_root: str) -> str | None:
    """
    若项目根存在 AGENTS.md 且尚未注入，注入一条 user message。

    Returns:
        注入文件的绝对路径（说明注入了）或 None（没注入）。
    """
    if has_injected_agents_md(messages):
        return None
    path = _find_agents_md(project_root)
    if not path:
        return None
    try:
        content = Path(path).read_text(encoding="utf-8")
    except Exception:
        return None

    # 长度保护：避免超长规则文件一次占满上下文
    max_chars = AGENT_CONFIG.agents_md_max_chars
    truncated = False
    if max_chars > 0 and len(content) > max_chars:
        content = (
            content[:max_chars]
            + f"\n\n...（AGENTS.md 超过 {max_chars} 字符，已截断，仅注入前 {max_chars} 字符）"
        )
        truncated = True

    # 构建注入消息 —— 用 user role（最稳妥，不会被模型忽略）
    injected = (
        f"{_AGENTS_MD_MARKER}\n\n"
        f"请严格遵守以下项目规则文件，它是项目团队所有工作的前置约束：\n\n"
        f"# AGENTS.md\n\n"
        f"{content.strip()}\n"
    )
    messages.append({"role": "user", "content": injected})
    return f"{path} (truncated)" if truncated else path
