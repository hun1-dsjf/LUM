"""
AnythingLLM MCP Server（streamable-http）。

把本机 AnythingLLM 的 HTTP API 封装为 MCP 工具，覆盖四类能力：
  - 工作区管理：list_workspaces / create_workspace
  - 对话问答：query_workspace
  - 文档上传与向量化：upload_document
  - 工作区文档查询：list_workspace_documents
"""

import json
import os
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()  # 从 .env 加载配置

ANYTHINGLLM_BASE = os.getenv("ANYTHINGLLM_BASE", "http://localhost:3001").rstrip("/")
ANYTHINGLLM_API_KEY = os.getenv("ANYTHINGLLM_API_KEY", "").strip()
ANYTHINGLLM_WORKSPACE_SLUG = os.getenv("ANYTHINGLLM_WORKSPACE_SLUG", "").strip()

# 允许上传的文档类型（AnythingLLM 支持的常见格式）
ALLOWED_EXTENSIONS = {
    ".txt", ".md", ".pdf", ".docx", ".doc", ".csv", ".json",
    ".html", ".htm", ".pptx", ".xlsx", ".epub",
}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

mcp = MCPServer("anythingllm-mcp")


# ========== HTTP 基础设施 ==========

class AnythingLLMError(RuntimeError):
    """AnythingLLM 调用失败（带可读原因）。"""


def _headers(extra: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {ANYTHINGLLM_API_KEY}"}
    if extra:
        headers.update(extra)
    return headers


def _request(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 30,
) -> dict:
    """统一 HTTP 调用：补齐鉴权、超时、错误映射。"""
    if not ANYTHINGLLM_API_KEY:
        raise AnythingLLMError(
            "未配置 ANYTHINGLLM_API_KEY。请在 AnythingLLM 的 Settings → API Keys 生成后写入 .env"
        )

    url = f"{ANYTHINGLLM_BASE}{path}"
    data = raw_body
    headers = _headers()
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if content_type:
        headers["Content-Type"] = content_type

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        hint = {
            401: "API Key 无效或缺失",
            403: "API Key 权限不足",
            404: "工作区或接口不存在",
            429: "请求过于频繁",
        }.get(exc.code, "上游返回错误")
        raise AnythingLLMError(f"{hint}（HTTP {exc.code}）：{detail}") from exc
    except urllib.error.URLError as exc:
        raise AnythingLLMError(
            f"无法连接 AnythingLLM（{ANYTHINGLLM_BASE}）：{exc.reason}。请确认服务已启动"
        ) from exc
    except TimeoutError as exc:
        raise AnythingLLMError(f"调用 AnythingLLM 超时（{timeout}s）") from exc

    try:
        return json.loads(body) if body else {}
    except json.JSONDecodeError:
        return {"raw": body}


def _resolve_slug(workspace_slug: str = "") -> str:
    """优先使用显式 slug，其次环境变量，最后自动取第一个工作区。"""
    slug = (workspace_slug or ANYTHINGLLM_WORKSPACE_SLUG).strip()
    if slug:
        return slug
    data = _request("GET", "/api/v1/workspaces", timeout=10)
    workspaces = data.get("workspaces") or []
    if not workspaces:
        raise AnythingLLMError("AnythingLLM 中还没有工作区，请先调用 create_workspace 创建")
    return workspaces[0].get("slug", "")


def _ok(payload: dict) -> str:
    return json.dumps({"ok": True, **payload}, ensure_ascii=False)


def _fail(message: str) -> str:
    return json.dumps({"ok": False, "error": message}, ensure_ascii=False)


# ========== 工具：工作区管理 ==========

@mcp.tool()
def list_workspaces() -> str:
    """列出 AnythingLLM 中所有工作区（名称、slug、文档数量）。"""
    try:
        data = _request("GET", "/api/v1/workspaces", timeout=10)
        items = [
            {
                "name": w.get("name", ""),
                "slug": w.get("slug", ""),
                "documents": len(
                    (w.get("documents") or []) + (w.get("workspaceDocuments") or [])
                ),
            }
            for w in data.get("workspaces", [])
        ]
        return _ok({"count": len(items), "workspaces": items})
    except AnythingLLMError as exc:
        return _fail(str(exc))


@mcp.tool()
def create_workspace(name: str) -> str:
    """创建一个新的 AnythingLLM 工作区。

    Args:
        name: 工作区名称（1-64 个字符）
    """
    name = (name or "").strip()
    if not name:
        return _fail("工作区名称不能为空")
    if len(name) > 64:
        return _fail("工作区名称不能超过 64 个字符")
    try:
        data = _request("POST", "/api/v1/workspace/new", payload={"name": name})
        workspace = data.get("workspace") or {}
        return _ok({"name": workspace.get("name", name), "slug": workspace.get("slug", "")})
    except AnythingLLMError as exc:
        return _fail(str(exc))


# ========== 工具：对话问答 ==========

@mcp.tool()
def query_workspace(message: str, workspace_slug: str = "") -> str:
    """向指定工作区提问，返回 AI 回答与参考来源。

    Args:
        message: 要向工作区提出的问题
        workspace_slug: 工作区 slug；留空则使用第一个工作区
    """
    message = (message or "").strip()
    if not message:
        return _fail("message 不能为空")
    try:
        slug = _resolve_slug(workspace_slug)
        data = _request(
            "POST",
            f"/api/v1/workspace/{urllib.parse.quote(slug)}/chat",
            payload={"message": message, "mode": "chat"},
            timeout=120,
        )
        sources = [s.get("title", "?") for s in (data.get("sources") or [])]
        return _ok(
            {
                "workspace": slug,
                "answer": data.get("textResponse", ""),
                "sources": sources,
            }
        )
    except AnythingLLMError as exc:
        return _fail(str(exc))


# ========== 工具：文档上传与向量化 ==========

@mcp.tool()
def upload_document(file_path: str, workspace_slug: str = "") -> str:
    """把一个本地文档上传到工作区并触发向量化（embed）。

    Args:
        file_path: 本地文件的绝对路径或相对路径
        workspace_slug: 目标工作区 slug；留空则使用第一个工作区
    """
    path = Path(file_path).expanduser()
    if not path.is_file():
        return _fail(f"文件不存在：{file_path}")
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return _fail(f"不支持的文件类型 {suffix}，允许：{', '.join(sorted(ALLOWED_EXTENSIONS))}")
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        return _fail(f"文件过大（{size} 字节），上限 {MAX_UPLOAD_BYTES} 字节")

    try:
        slug = _resolve_slug(workspace_slug)
        boundary = f"----anythingllm-mcp-{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = bytearray()

        def _field(name: str, value: str) -> None:
            body.extend(f"--{boundary}\r\n".encode())
            body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
            body.extend(value.encode("utf-8"))
            body.extend(b"\r\n")

        _field("addToWorkspaces", slug)
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'.encode(
                "utf-8"
            )
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(path.read_bytes())
        body.extend(f"\r\n--{boundary}--\r\n".encode())

        data = _request(
            "POST",
            "/api/v1/document/upload",
            raw_body=bytes(body),
            content_type=f"multipart/form-data; boundary={boundary}",
            timeout=180,
        )
        documents = data.get("documents") or []
        return _ok(
            {
                "workspace": slug,
                "file": path.name,
                "size_bytes": size,
                "uploaded": len(documents),
                "documents": [
                    {"title": d.get("title", ""), "location": d.get("location", "")}
                    for d in documents
                ],
            }
        )
    except (AnythingLLMError, OSError) as exc:
        return _fail(str(exc))


# ========== 工具：工作区文档查询 ==========

@mcp.tool()
def list_workspace_documents(workspace_slug: str = "") -> str:
    """列出指定工作区已向量化的文档。

    Args:
        workspace_slug: 工作区 slug；留空则使用第一个工作区
    """
    try:
        slug = _resolve_slug(workspace_slug)
        data = _request("GET", f"/api/v1/workspace/{urllib.parse.quote(slug)}", timeout=15)
        docs = (data.get("workspace") or {}).get("documents") or []
        items = [
            {"title": d.get("title", ""), "url": d.get("url", ""), "token_count": d.get("token_count_estimate")}
            for d in docs
        ]
        return _ok({"workspace": slug, "count": len(items), "documents": items})
    except AnythingLLMError as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    if not ANYTHINGLLM_API_KEY:
        print(
            "[anythingllm-mcp] 警告：未设置 ANYTHINGLLM_API_KEY，工具调用将返回配置错误。",
        )
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8765)
