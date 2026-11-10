"""
时间与闰年工具。

提供两个真实可执行、跨平台的工具：
  - getCurrentTime：返回当前日期时间（本地时区或 IANA 时区）
  - isLeapYear：按公历规则判断闰年（整百年需被 400 整除）
"""
from __future__ import annotations

import json
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None  # type: ignore


def _error(message: str) -> str:
    return json.dumps({"error": message}, ensure_ascii=False)


def tool_get_current_time(args: dict) -> str:
    """返回当前日期时间。args: {"timezone": "local" | "Asia/Shanghai" | "UTC"}"""
    tz_name = str(args.get("timezone", "local") or "local").strip()
    try:
        if tz_name.lower() in ("local", "system", ""):
            now = datetime.now().astimezone()
        elif tz_name.upper() == "UTC":
            from datetime import timezone
            now = datetime.now(timezone.utc)
        else:
            if ZoneInfo is None:
                return _error("当前 Python 版本不支持 zoneinfo，请使用 local 或 UTC")
            now = datetime.now(ZoneInfo(tz_name))
    except Exception as exc:
        return _error(f"无效时区 '{tz_name}'：{exc}")

    return json.dumps(
        {
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "iso8601": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": now.strftime("%A"),
            "weekday_cn": "一二三四五六日"[now.weekday()],
            "timezone": tz_name if tz_name.lower() != "local" else str(now.tzinfo),
            "unix_timestamp": int(now.timestamp()),
        },
        ensure_ascii=False,
    )


def tool_is_leap_year(args: dict) -> str:
    """按公历规则判断闰年。args: {"year": 2024}"""
    raw = args.get("year")
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return _error(f"year 必须是整数，收到 {raw!r}")
    if not 1 <= year <= 9999:
        return _error("year 必须在 1..9999 之间")

    is_leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    return json.dumps(
        {
            "year": year,
            "isLeapYear": is_leap,
            "daysInYear": 366 if is_leap else 365,
            "daysInFebruary": 29 if is_leap else 28,
            "rule": "能被 4 整除且不能被 100 整除，或能被 400 整除",
        },
        ensure_ascii=False,
    )


TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "getCurrentTime",
            "description": (
                "获取当前日期时间。默认返回本机本地时区；也可传 IANA 时区名（如 Asia/Shanghai、"
                "UTC）。凡是涉及“今天/现在/当前时间”的问题都应先调用本工具，禁止凭记忆回答。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "时区名，默认 local；可选 local / UTC / Asia/Shanghai 等 IANA 名称",
                        "default": "local",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": (
                "判断指定年份是否为闰年，并返回该年天数与二月天数。"
                "公历规则：能被 4 整除且不能被 100 整除，或能被 400 整除。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {
                        "type": "integer",
                        "description": "待判断的年份，范围 1..9999",
                        "minimum": 1,
                        "maximum": 9999,
                    }
                },
                "required": ["year"],
                "additionalProperties": False,
            },
        },
    },
]

TOOL_MAP = {
    "getCurrentTime": tool_get_current_time,
    "isLeapYear": tool_is_leap_year,
}
