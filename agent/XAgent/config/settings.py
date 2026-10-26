"""配置加载：.env（LLM 主密钥）+ config.ini（搜索等辅助配置）。"""
from __future__ import annotations

import configparser
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# XAgent 根目录
XAGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 加载 .env
load_dotenv(os.path.join(XAGENT_ROOT, ".env"))

# 加载 config.ini（可选，某些功能如搜索需要）
_ini = configparser.ConfigParser()
_ini.read(os.path.join(XAGENT_ROOT, "config.ini"), encoding="utf-8-sig")


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = os.getenv("API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "缺少 API_KEY 环境变量：请在 XAgent/.env 中填入真实密钥"
            )
        return cls(
            api_key=api_key,
            base_url=os.getenv("BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.getenv("MODEL", "deepseek-chat"),
        )


@dataclass(frozen=True)
class SearchConfig:
    """百度千帆搜索 API 配置（从 config.ini [search] 小节读取）。"""
    api_key: str
    endpoint: str
    top_k: int
    edition: str

    @classmethod
    def from_ini(cls) -> "SearchConfig | None":
        """读取 config.ini；若缺少 [search] 小节或 key，返回 None（表示搜索不可用）。"""
        if not _ini.has_section("search"):
            return None
        key = _ini.get("search", "baidu_qianfan_api_key", fallback="").strip()
        if not key:
            return None
        return cls(
            api_key=key,
            endpoint=_ini.get("search", "qianfan_endpoint",
                              fallback="https://qianfan.baidubce.com/v2/ai_search/web_search").strip(),
            top_k=_ini.getint("search", "search_top_k", fallback=10),
            edition=_ini.get("search", "search_edition", fallback="standard").strip(),
        )


# 沙箱根目录
SANDBOX_ROOT = XAGENT_ROOT
