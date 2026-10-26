"""
网页内容获取工具 —— fetchWeb。

流程：
  1. subprocess 调用 curl.exe 下载 HTML（参数列表方式，shell=False）
  2. trafilatura 提取正文 + 转换为 Markdown

依赖：curl.exe（Windows 自带）、trafilatura（pip install trafilatura）
"""
from __future__ import annotations

import subprocess
from urllib.parse import urlparse

try:
    import trafilatura
except ImportError:
    trafilatura = None


# ========== 工具实现 ==========

# 请求超时（秒）
_FETCH_TIMEOUT = 20
# 返回内容最大长度（字符），超出截断
_MAX_CONTENT_LEN = 8000


def _validate_url(url: str) -> str | None:
    """简单 URL 校验，返回错误描述或 None。"""
    if not url or not url.strip():
        return "URL 不能为空"
    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return f"URL 格式无效: {url!r}"
    if parsed.scheme not in ("http", "https"):
        return f"仅支持 http/https，收到: {parsed.scheme!r}"
    if not parsed.netloc:
        return f"URL 缺少域名: {url!r}"
    # 拒绝本机/内网 IP 防 SSRF（允许 localhost 方便测试）
    host = parsed.netloc.split(":")[0].lower()
    if host in ("127.0.0.1", "0.0.0.0"):
        return f"禁止访问内网地址: {host}"
    if host.startswith("192.168.") or host.startswith("10.") or host.startswith("172."):
        # 172.16-31 是内网，粗筛
        if host.startswith("172.") and not (16 <= int(host.split(".")[1]) <= 31):
            pass
        else:
            return f"禁止访问内网地址: {host}"
    return None


def _download_html(url: str) -> tuple[str | None, str | None]:
    """
    用 curl.exe 下载 HTML。返回 (html_text, error_msg)，二选一。

    采用参数列表方式调用，不用 shell=True，避免命令注入。
    """
    args = [
        "curl.exe",
        "-sS",           # 静默但显示错误
        "-L",            # 跟随重定向
        "--max-time", str(_FETCH_TIMEOUT),
        "--connect-timeout", "10",
        "-H", "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0",
        "-H", "Accept-Language: zh-CN,zh;q=0.9",
        "-H", "Accept: text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "-o", "-",       # stdout
        url,
    ]

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=_FETCH_TIMEOUT + 5,
            encoding="utf-8", errors="replace",
        )
    except subprocess.TimeoutExpired:
        return None, f"请求超时（超过 {_FETCH_TIMEOUT + 5} 秒）"
    except FileNotFoundError:
        return None, "curl.exe 未找到：请确认系统 PATH 中包含 curl"
    except OSError as e:
        return None, f"启动 curl 失败: {e}"

    if result.returncode != 0:
        stderr = result.stderr.strip() or "(无错误输出)"
        return None, f"curl 返回码 {result.returncode}: {stderr}"

    html = result.stdout
    if not html.strip():
        return None, "curl 返回空内容"

    return html, None


def _extract_markdown(html: str) -> tuple[str | None, str | None]:
    """用 trafilatura 提取正文并转换为 Markdown。"""
    if trafilatura is None:
        return None, "trafilatura 库未安装：请 pip install trafilatura"

    try:
        # include_links / include_tables 保留结构格式
        md = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_images=False,    # 图片链接耗 token 且不可见
            favor_precision=True,    # 宁愿少提取也不要噪音
        )
    except Exception as e:
        return None, f"trafilatura 解析失败: {e}"

    if not md or not md.strip():
        return None, "未能从页面中提取到有效正文（可能是 JS 渲染页或纯导航页）"

    return md.strip(), None


def tool_fetch_web(args: dict) -> str:
    """fetchWeb 工具入口：下载网页 → 提取 Markdown → 返回。"""
    url = (args.get("url") or "").strip()

    # 1. URL 校验
    err = _validate_url(url)
    if err:
        return f"抓取失败: {err}"

    # 2. 下载 HTML
    html, err = _download_html(url)
    if err:
        return f"抓取失败: {err}"

    # 3. 提取 Markdown
    md, err = _extract_markdown(html)
    if err:
        return f"抓取失败: {err}"

    # 4. 截断保护
    if len(md) > _MAX_CONTENT_LEN:
        md = md[:_MAX_CONTENT_LEN] + "\n\n...（内容已截断，原文过长）"

    return f"来源: {url}\n\n{md}"


# ========== 工具注册 ==========

FETCH_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "fetchWeb",
            "description": (
                "抓取指定网页的正文内容并转换为 Markdown。"
                "会自动去除导航栏、广告、页脚等无关元素，保留标题/段落/列表/表格/链接。"
                "当 searchWeb 找到搜索结果后，如果你需要更详细的某条结果内容，"
                "可以对那个 URL 调用 fetchWeb。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要抓取的网页 URL（仅支持 http/https）",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    }
]

FETCH_TOOL_MAP = {
    "fetchWeb": tool_fetch_web,
}
