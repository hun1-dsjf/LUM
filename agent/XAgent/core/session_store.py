"""
会话持久化 —— JSON 行格式，与 context_manager 的归档格式兼容。

会话结构（每条 message 一行）：
  {"role": "system", "content": "..."}
  {"role": "user", "content": "你好"}
  {"role": "assistant", "content": "嗨", "tool_calls": [...]}
  {"role": "tool", "tool_call_id": "call_1", "content": "result"}

会话元数据（单独 .meta.json）：
  {"id": "20261104-153000", "title": "排八字", "created": "ISO", "updated": "ISO",
   "messages_count": 42, "summary": "..."}

存储目录: <work_root>/.agents/sessions/
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from config.config_manager import AGENT_CONFIG


def _sessions_dir() -> Path:
    p = Path(AGENT_CONFIG.sessions_dir_abs)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_title(s: str) -> str:
    """把一段自然语言标题转为安全文件名（截断 + 替换非法字符）。"""
    import re
    s = re.sub(r"[\\/:*?\"<>|\r\n\t]+", "_", s).strip()
    return s[:40] or "untitled"


def new_session_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


class SessionStore:
    """会话管理：save / load / list / delete / rename。"""

    @staticmethod
    def new_id() -> str:
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    # Python 允许属性转发，给调用方两种写法
    new_session_id = staticmethod(lambda: datetime.now().strftime("%Y%m%d-%H%M%S"))

    @staticmethod
    def _session_paths(sid: str) -> tuple[Path, Path]:
        d = _sessions_dir()
        return d / f"{sid}.jsonl", d / f"{sid}.meta.json"

    # ---------- 写 ----------

    @staticmethod
    def save(sid: str, messages: list[dict], title: str = "") -> None:
        msg_path, meta_path = SessionStore._session_paths(sid)
        # 原子写
        tmp = msg_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for m in messages:
                obj = {k: v for k, v in m.items()
                       if k in ("role", "content", "tool_calls", "tool_call_id")}
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        os.replace(tmp, msg_path)

        meta = {
            "id": sid,
            "title": title or _safe_title(next(
                (m.get("content", "") for m in messages if m.get("role") == "user"),
                "untitled",
            ) if messages else "untitled"),
            "created": sid,
            "updated": datetime.now().isoformat(timespec="seconds"),
            "messages_count": len(messages),
        }
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    # ---------- 读 ----------

    @staticmethod
    def load(sid: str) -> list[dict] | None:
        msg_path, _ = SessionStore._session_paths(sid)
        if not msg_path.is_file():
            return None
        msgs = []
        with open(msg_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    msgs.append(json.loads(line))
        return msgs

    @staticmethod
    def load_meta(sid: str) -> dict | None:
        _, meta_path = SessionStore._session_paths(sid)
        if not meta_path.is_file():
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # ---------- 列表 ----------

    @staticmethod
    def list() -> list[dict]:
        items = []
        for f in sorted(_sessions_dir().glob("*.meta.json"), reverse=True):
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    meta = json.load(fp)
                items.append(meta)
            except Exception:
                continue
        return items

    # ---------- 删除 ----------

    @staticmethod
    def delete(sid: str) -> bool:
        msg_path, meta_path = SessionStore._session_paths(sid)
        ok = False
        for p in (msg_path, meta_path):
            if p.is_file():
                try: p.unlink(); ok = True
                except Exception: pass
        return ok
