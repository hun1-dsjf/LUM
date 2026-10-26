"""
网络搜索工具 —— 通过百度千帆 web_search API 联网搜索。

API 文档: https://cloud.baidu.com/doc/qianfan-api/s/Wmbq4z7e5
鉴权: Authorization: Bearer <API Key>（Key 前缀通常为 bce-v3/）

请求: POST https://qianfan.baidubce.com/v2/ai_search/web_search
响应: {
  "references": [
    {"title", "url", "snippet", "date", "website"}
  ]
}
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from config.settings import SearchConfig

# ========== 配置初始化 ==========

_search_cfg = SearchConfig.from_ini()


# ========== 工具实现 ==========

def _call_qianfan(query: str, top_k: int = 10) -> dict:
    """
    调用百度千帆 web_search API，返回解析后的 references 列表或错误信息。

    返回格式（成功时）: [{"title": ..., "url": ..., "snippet": ..., "date": ..., "website": ...}]
    返回格式（失败时）: {"error": "错误描述"}
    """
    global _search_cfg
    if _search_cfg is None:
        return {"error": "搜索功能未配置：请在 config.ini 的 [search] 小节填入 baidu_qianfan_api_key"}

    if not query or not query.strip():
        return {"error": "搜索关键词不能为空"}

    body = {
        "messages": [{"role": "user", "content": query.strip()}],
        "search_source": "baidu_search_v2",
        "edition": _search_cfg.edition,
        "resource_type_filter": [{"type": "web", "top_k": min(top_k, 20)}],
    }

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _search_cfg.endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {_search_cfg.api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            pass
        return {"error": f"HTTP {e.code}: {detail or e.reason}"}
    except urllib.error.URLError as e:
        return {"error": f"网络连接失败: {e.reason}"}
    except json.JSONDecodeError as e:
        return {"error": f"API 返回非 JSON: {e}"}
    except OSError as e:
        return {"error": f"请求超时或网络异常: {e}"}

    # 百度 API 错误码走顶层 code/message 字段
    if "code" in payload and payload["code"] not in (0, "0", None):
        return {"error": f"百度千帆错误 {payload.get('code')}: {payload.get('message')}"}

    return payload.get("references", [])


def tool_search_web(args: dict) -> str:
    """searchWeb 工具入口：调用搜索 API 并整理返回结果。"""
    query = (args.get("query") or "").strip()
    top_k = int(args.get("top_k", 10))

    result = _call_qianfan(query, top_k)

    if isinstance(result, dict) and "error" in result:
        return f"搜索失败: {result['error']}"

    if not result:
        return f"搜索未返回任何结果（query={query!r}）"

    lines = [f"搜索关键词: {query}", f"找到 {len(result)} 条结果:\n"]
    for i, ref in enumerate(result, 1):
        title = ref.get("title") or "(无标题)"
        url = ref.get("url") or "(无链接)"
        snippet = (ref.get("snippet") or ref.get("content") or "").strip()
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        date = ref.get("date") or ""
        site = ref.get("website") or ""
        meta_parts = [p for p in [site, date] if p]
        meta = f" [{', '.join(meta_parts)}]" if meta_parts else ""
        lines.append(f"{i}. {title}{meta}")
        lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   摘要: {snippet}")
        lines.append("")

    return "\n".join(lines).rstrip()


# ========== 工具注册 ==========

SEARCH_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "searchWeb",
            "description": (
                "联网搜索实时信息。当用户需要最新资讯、当前事件、外部知识、"
                "实时数据等你不知道的信息时，调用此工具获取搜索结果（标题+摘要+URL）。"
                "注意：搜索结果只是信息来源，你需要基于这些内容给出自己的总结。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或自然语言问题（最多 72 字符）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果条数，默认 10，最多 20",
                        "default": 10,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]

SEARCH_TOOL_MAP = {
    "searchWeb": tool_search_web,
}
