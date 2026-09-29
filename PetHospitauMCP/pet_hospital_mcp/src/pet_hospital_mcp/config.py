"""Runtime configuration loaded from environment variables.

All values have safe localhost-only defaults suitable for the local
teaching scenario. No auth, CORS, or origin validation is configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000
DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8080"
DEFAULT_BACKEND_TIMEOUT_SECONDS = 10.0
DEFAULT_BACKEND_RETRIES = 1  # one retry on timeout / 5xx (total 2 attempts)


def _env_str(key: str, default: str) -> str:
    v = os.environ.get(key)
    return v.strip() if v and v.strip() else default


def _env_int(key: str, default: int) -> int:
    v = os.environ.get(key)
    if not v or not v.strip():
        return default
    try:
        return int(v.strip())
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    v = os.environ.get(key)
    if not v or not v.strip():
        return default
    try:
        return float(v.strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration."""

    mcp_host: str
    mcp_port: int
    mcp_http_path: str
    backend_base_url: str
    backend_timeout_seconds: float
    backend_retries: int

    @property
    def mcp_url(self) -> str:
        return f"http://{self.mcp_host}:{self.mcp_port}{self.mcp_http_path}"


def load_config() -> Config:
    """Read configuration from environment variables."""
    return Config(
        mcp_host=_env_str("MCP_HOST", DEFAULT_MCP_HOST),
        mcp_port=_env_int("MCP_PORT", DEFAULT_MCP_PORT),
        mcp_http_path=_env_str("MCP_HTTP_PATH", "/mcp"),
        backend_base_url=_env_str(
            "PET_HOSPITAL_BASE_URL", DEFAULT_BACKEND_BASE_URL
        ).rstrip("/"),
        backend_timeout_seconds=_env_float(
            "PET_HOSPITAL_TIMEOUT", DEFAULT_BACKEND_TIMEOUT_SECONDS
        ),
        backend_retries=_env_int("PET_HOSPITAL_RETRIES", DEFAULT_BACKEND_RETRIES),
    )
