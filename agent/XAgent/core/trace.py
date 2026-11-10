"""
结构化调用追踪。

每次工具调用、工具结果、异常与轮次结束都会追加一行 JSON 到
`<XAgent根>/.agents/logs/YYYYMMDD.jsonl`，便于复盘 Agent 行为。
写日志失败不会影响主流程（静默降级）。
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime

from config.config_manager import AGENT_CONFIG

_lock = threading.Lock()


def trace(event: str, **fields) -> None:
    """追加一条 JSONL 追踪记录；任何异常都被吞掉。"""
    if not AGENT_CONFIG.trace_enabled:
        return
    try:
        now = datetime.now()
        record = {"ts": now.isoformat(timespec="milliseconds"), "event": event}
        record.update(fields)
        os.makedirs(AGENT_CONFIG.trace_dir_abs, exist_ok=True)
        path = os.path.join(AGENT_CONFIG.trace_dir_abs, f"{now:%Y%m%d}.jsonl")
        line = json.dumps(record, ensure_ascii=False, default=str)
        with _lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass
