"""Structured JSON logging with recursive redaction of sensitive fields.

Required log fields: ``timestamp``, ``tool_name``, ``params``, ``status``,
``duration_ms``. The fields ``ownerPhone`` / ``ownerAddr`` / ``chipNo`` (and
their snake_case spellings) are recursively replaced with ``"***REDACTED***"``
anywhere in a logged mapping, so complete sensitive values never reach logs.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any

# Field names to redact, case-insensitively, in both camelCase and snake_case.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "ownerphone",
        "owner_phone",
        "owneraddr",
        "owner_addr",
        "chipno",
        "chip_no",
    }
)

_REDACTED = "***REDACTED***"


def redact(value: Any) -> Any:
    """Recursively redact sensitive keys in mappings / lists / tuples."""
    if isinstance(value, dict):
        return {
            (k if k.lower() in SENSITIVE_KEYS else k): (
                _REDACTED if k.lower() in SENSITIVE_KEYS else redact(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        seq = [redact(v) for v in value]
        return type(value)(seq) if isinstance(value, tuple) else seq  # type: ignore[return-value]
    return value


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per log record."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge LogRecord extras (e.g. tool_name, params, status, duration_ms).
        for key, value in record.__dict__.items():
            if key in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process",
                "taskName",
            }:
                continue
            payload[key] = value
        payload = {k: redact(v) for k, v in payload.items()}
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str | int | None = None) -> None:
    """Configure root logging to emit JSON to stdout. Idempotent."""
    if level is None:
        level = os.environ.get("MCP_LOG_LEVEL", "INFO")
    root = logging.getLogger()
    # Clear any pre-existing handlers to keep output deterministic.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
