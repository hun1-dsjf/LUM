"""
上下文管理器 —— Token 计算、归档、LLM 摘要压缩、历史检索。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from config.config_manager import AGENT_CONFIG


# =========================================================
# 压缩专用 Prompt（硬编码）
# =========================================================
COMPACT_SYSTEM_PROMPT = (
    "你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，"
    "需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。"
)

COMPACT_USER_PROMPT_TEMPLATE = """请认真阅读下面提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：
1. 用户目标与要求
2. 已经完成的工作
3. 当前工作状态
4. 关键技术信息（文件路径、函数名、配置等准确原文）
5. 关键决策与原因
6. 下一步任务

请遵守：
- 优先保留有直接影响的信息，删除寒暄和无关内容。
- 区分已验证事实与推测。
- 不要将计划描述为已完成。
- 如果信息冲突，保留用户最新确认的要求。
- 使用清晰的 Markdown 输出。
- 最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能继续开展工作。

--- 历史上下文开始 ---
{history_text}
--- 历史上下文结束 ---

请直接输出 Markdown 摘要，不要任何前言或解释。"""


# =========================================================
# Token 估算
# =========================================================

def estimate_tokens(text: str) -> int:
    """粗略估算 Token 数：英文 ~4 char/token，中文 ~1.5 char/token，合并约 2.5 char/token。"""
    if not text:
        return 0
    return max(1, len(text) // 2)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算 messages 列表的总 Token 数。"""
    total = 0
    for msg in messages:
        # role 成本 ~4 tokens
        total += 4
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # 多模态 list 取 text 项
            for item in content:
                if isinstance(item, dict):
                    total += estimate_tokens(str(item))
        # tool_calls 里的 arguments / name
        for tc in msg.get("tool_calls", []) or []:
            fn = (tc.get("function") or {})
            total += estimate_tokens(fn.get("name", ""))
            total += estimate_tokens(fn.get("arguments", ""))
        # role=tool 的 tool_call_id
        if msg.get("role") == "tool":
            total += estimate_tokens(msg.get("tool_call_id", ""))
    return total


# =========================================================
# 上下文目录 & 归档
# =========================================================

def _find_context_dir() -> Path:
    """向上查找 .agents/context/ 目录，找不到则创建（与 skill_loader 策略一致）。"""
    cursor = Path(os.getcwd()).resolve()
    for _ in range(20):
        candidate = cursor / ".agents" / "context"
        try:
            cursor.mkdir(parents=True, exist_ok=True)
            context_dir = cursor / ".agents" / "context"
            context_dir.mkdir(parents=True, exist_ok=True)
            return context_dir
        except OSError:
            pass
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    # 兜底用 cwd 下的 .agents/context
    fallback = Path.cwd() / ".agents" / "context"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def archive_messages(messages: list[dict]) -> tuple[str, Path]:
    """
    将当前会话导出为 .jsonl 文件。一行一条原始 message（保留 role/content/tool_calls 完整结构）。

    Returns:
        (archive_id, file_path) —— archive_id 形如 "20261104-153000"
    Raises:
        OSError —— 保存失败时抛出，由上层决定是否中止压缩
    """
    context_dir = _find_context_dir()
    archive_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    # 防止同一秒内重复
    base = archive_id
    i = 0
    while True:
        suffix = f"-{i}" if i > 0 else ""
        fname = f"{archive_id}{suffix}.jsonl"
        full = context_dir / fname
        if not full.exists():
            archive_id = f"{base}{suffix}"
            break
        i += 1

    # 先写临时文件，写完再 rename（原子性）
    tmp_path = full.with_suffix(".jsonl.tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            for msg in messages:
                # 写一个精简的 JSON（避免过度冗余）
                line_obj = {
                    "role": msg.get("role"),
                }
                if "content" in msg and msg["content"] is not None:
                    line_obj["content"] = msg["content"]
                if "tool_calls" in msg and msg["tool_calls"]:
                    line_obj["tool_calls"] = msg["tool_calls"]
                if "tool_call_id" in msg:
                    line_obj["tool_call_id"] = msg["tool_call_id"]
                f.write(json.dumps(line_obj, ensure_ascii=False) + "\n")
        os.replace(tmp_path, full)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    return archive_id, full


def load_archive(archive_id: str) -> list[dict] | None:
    """根据 archive_id 加载对应 .jsonl 文件，返回 messages 列表。找不到返回 None。"""
    context_dir = _find_context_dir()
    # 支持 "20261104-153000" / "20261104-153000.jsonl" / 绝对路径 三种形式
    candidates: list[Path] = []
    if archive_id.endswith(".jsonl"):
        candidates.append(context_dir / archive_id)
        candidates.append(Path(archive_id))
    else:
        candidates.append(context_dir / f"{archive_id}.jsonl")
    for c in candidates:
        if c.is_file():
            msgs = []
            with open(c, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        msgs.append(json.loads(line))
            return msgs
    return None


def list_archives() -> list[dict]:
    """列出所有归档文件，返回 [{id, path, size, mtime}, ...]，按时间倒序。"""
    context_dir = _find_context_dir()
    items = []
    for f in sorted(context_dir.glob("*.jsonl"), reverse=True):
        stat = f.stat()
        items.append({
            "id": f.stem,
            "path": str(f.resolve()),
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        })
    return items


# =========================================================
# 历史检索（recallContext）
# =========================================================

def recall_context(
    keyword: str,
    archive_id: str | None = None,
    max_chars_per_archive: int = 4000,
) -> str:
    """
    遍历归档文件做关键字检索。

    Args:
        keyword: 要搜索的关键词（大小写不敏感）
        archive_id: 指定归档编号（可选，None=所有归档）
        max_chars_per_archive: 每个归档最多返回的字符数（防止撑爆上下文）

    Returns:
        拼接后的 Markdown 文本，包含命中的 archive_id 和片段。
        找不到任何东西时返回 "(无匹配结果)"。
    """
    keyword_lower = keyword.lower()
    results: list[str] = []

    if archive_id:
        archives_to_search = [archive_id]
    else:
        archives_to_search = [a["id"] for a in list_archives()]

    for aid in archives_to_search:
        msgs = load_archive(aid)
        if not msgs:
            continue

        # 在所有 content + tool arguments + tool_call results 里搜
        hits: list[str] = []
        for idx, msg in enumerate(msgs):
            text_parts: list[str] = []
            content = msg.get("content") or ""
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text_parts.append(str(item))
            for tc in msg.get("tool_calls", []) or []:
                fn = (tc.get("function") or {})
                text_parts.append(fn.get("name", ""))
                text_parts.append(fn.get("arguments", ""))
            combined = "\n".join(text_parts).strip()
            if combined and keyword_lower in combined.lower():
                # 截取命中行前后 200 字符的上下文
                pos = combined.lower().find(keyword_lower)
                start = max(0, pos - 200)
                end = min(len(combined), pos + len(keyword) + 200)
                snippet = combined[start:end].replace("\n", " ")
                hits.append(f"- [{idx}] {snippet}")

        if hits:
            results.append(f"### 归档 {aid}\n" + "\n".join(hits[:20]))  # 最多 20 条/归档

    if not results:
        return "(无匹配结果)"

    # 限制总长度
    full = "\n\n".join(results)
    if len(full) > max_chars_per_archive * len(archives_to_search):
        full = full[: max_chars_per_archive * len(archives_to_search)] + "\n...（已截断）"
    return full


# =========================================================
# LLM 摘要生成
# =========================================================

async def generate_summary(
    client,          # AsyncOpenAI 实例
    model: str,      # 模型名
    messages: list[dict],
) -> str:
    """
    调用 LLM 生成摘要。失败时抛出异常（由上层捕获，保留原 messages）。

    最小化请求体：只取 user/assistant/tool 的文本内容拼成 history_text，
    避免把 system prompt 和 tool_calls schema 也塞进去。
    """
    # 拼 history_text —— 跳过 system（它会在摘要生成的 system prompt 里覆盖）
    history_lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "")
        if role == "system":
            continue
        if role == "assistant":
            # 跳过 tool_calls 字段（它们只是"模型打算调什么"，压缩后没用）
            content = msg.get("content") or ""
            if content:
                history_lines.append(f"[assistant] {content}")
            for tc in msg.get("tool_calls", []) or []:
                fn = tc.get("function") or {}
                history_lines.append(f"[assistant: tool_call] {fn.get('name')}({fn.get('arguments', '')})")
        elif role == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            content = msg.get("content") or ""
            history_lines.append(f"[tool result] ({tool_call_id}) {content}")
        elif role == "user":
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = " ".join(str(x) for x in content)
            history_lines.append(f"[user] {content}")

    history_text = "\n".join(history_lines)
    user_prompt = COMPACT_USER_PROMPT_TEMPLATE.format(history_text=history_text)

    # 注意：不传 stream，要完整响应；不要 stream_options
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=AGENT_CONFIG.compact_temperature,
    )
    return response.choices[0].message.content or "(摘要为空)"


# =========================================================
# 主压缩流程（原子操作）
# =========================================================

async def perform_compaction(
    client,
    model: str,
    messages: list[dict],
    window_size: int | None = None,
) -> tuple[list[dict], str]:
    """
    原子压缩流程：归档 → 生成摘要 → 替换 messages。
    window_size=None 时从 AGENT_CONFIG 取默认值。
    """
    if window_size is None:
        window_size = AGENT_CONFIG.window_size
    # 1. 先归档（必须成功）
    archive_id, archive_path = archive_messages(messages)
    print(f"[context] ✅ 归档 {archive_id} → {archive_path}", file=sys.stderr, flush=True)

    # 2. 调 LLM 生成摘要（失败时保留原 messages）
    summary_md = await generate_summary(client, model, messages)
    summary_md = summary_md.strip()
    print(f"[context] ✅ 摘要生成完成，约 {len(summary_md)} 字符", file=sys.stderr, flush=True)

    # 3. 组装新 messages（只保留 system + 摘要 user）
    system_prompt = next((m for m in messages if m.get("role") == "system"), None)
    new_messages: list[dict] = []
    if system_prompt:
        new_messages.append(system_prompt)

    archive_block = (
        f"## 🔖 会话归档（{archive_id}）\n"
        f"- 归档文件：`{archive_path.name}`\n"
        f"- 若需查看完整原始历史，请使用 recallContext 工具，或查阅 .agents/context/ 目录\n\n"
        f"---\n\n"
        f"{summary_md}"
    )

    new_messages.append({"role": "user", "content": archive_block})

    # 验证替换后的 Token 数
    new_tokens = estimate_messages_tokens(new_messages)
    pct = new_tokens / window_size * 100
    print(f"[context] ✅ 替换完成：{len(messages)} → {len(new_messages)} 条，"
          f"Token {new_tokens:,} / {window_size:,} ({pct:.1f}%)", file=sys.stderr, flush=True)

    return new_messages, archive_id
