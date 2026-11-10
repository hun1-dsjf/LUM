"""
上下文检索工具集：recallContext（从归档中按关键字检索历史片段）。
"""
from __future__ import annotations

from typing import Callable

from core.context_manager import (
    list_archives,
    load_archive,
    recall_context,
)

# ---------- recallContext ----------

def tool_recall_context(args: dict) -> str:
    """
    recallContext 实现。JSON RPC 风格：成功返回纯文本，错误返回 JSON 错误体。
    """
    archive_id = args.get("archiveId") or args.get("archive_id")
    keyword = args.get("keyword") or args.get("query") or args.get("text")

    # 列出所有归档 —— 无参数且无关键字时
    if not archive_id and not keyword:
        archives = list_archives()
        if not archives:
            return "（当前没有任何会话归档。等您执行 /compact 后，归档会自动保存在 .agents/context/ 下。）"
        lines = ["## 可用会话归档\n"]
        for a in archives:
            lines.append(f"- `{a['id']}` — {a['mtime']} ({a['size']:,} 字节)")
        lines.append("\n💡 用法：recallContext(archiveId='20261104-153000') 查看某份归档；或带 keyword 全文搜索。")
        return "\n".join(lines)

    # 指定了 archive_id 但没 keyword —— 返回该归档的基本信息 + 前 1500 字符
    if archive_id and not keyword:
        msgs = load_archive(archive_id)
        if msgs is None:
            return f"（归档 `{archive_id}` 不存在。可用 archive 列表：{[a['id'] for a in list_archives()]}）"
        # 拼接前几条作为预览
        prev_lines = [f"## 归档 {archive_id}（共 {len(msgs)} 条消息）\n"]
        for m in msgs[:10]:
            role = m.get("role", "?")
            content = m.get("content", "") or ""
            if isinstance(content, str) and len(content) > 200:
                content = content[:200] + "…"
            if content:
                prev_lines.append(f"- **{role}**: {content}")
        if len(msgs) > 10:
            prev_lines.append(f"\n… 还有 {len(msgs) - 10} 条。可以用 keyword 搜索具体内容。")
        return "\n".join(prev_lines)

    # 关键字检索
    result = recall_context(keyword=keyword or "", archive_id=archive_id)
    if result == "(无匹配结果)":
        scoped = f"（在归档 `{archive_id}` 中搜索）" if archive_id else "（在所有归档中搜索）"
        return f"未找到包含 **{keyword}** 的片段 {scoped}。\n💡 可用 archive 列表：{[a['id'] for a in list_archives()]}"
    return result


# ---------- 注册表 ----------

CONTEXT_TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "recallContext",
            "description": (
                "从 .agents/context/ 下的历史归档（.jsonl）中按关键字检索过去对话的片段。"
                "支持三种用法："
                "① 不带任何参数调用——列出所有可用归档；"
                "② 只传 archiveId——预览指定归档的前几条；"
                "③ 传 keyword（可同时传 archiveId 限定范围）——全文关键字检索，返回命中片段。"
                "当 Agent 需要回忆更早之前聊过的内容、或 compact 后丢了原始上下文时，应优先调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "archiveId": {
                        "type": "string",
                        "description": "指定归档编号，如 '20261104-153000'（可选）",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "要搜索的关键字（大小写不敏感，可选）",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
]

CONTEXT_TOOL_MAP: dict[str, Callable[[dict], str]] = {
    "recallContext": tool_recall_context,
}
