# AnythingLLM MCP Server

通过 MCP 协议访问本机 AnythingLLM 的 HTTP API，提供 **工作区管理、对话问答、文档上传向量化、工作区文档查询** 四类工具。

## 项目位置

```
AnythingLLMMCP/
├── server.py          # MCP Server（streamable-http，端口 8765）
├── requirements.txt   # mcp + python-dotenv
└── .env.example       # 配置模板
```

## 前置条件

- Python 3.10+（推荐 3.13）
- 本机运行 AnythingLLM（默认 `http://localhost:3001`）
- 在 AnythingLLM 的 **Settings → API Keys** 中生成 API Key

## 安装依赖

```bash
cd AnythingLLMMCP
pip install -r requirements.txt
```

## 配置

复制模板并填入真实配置（`.env` 已被 `.gitignore` 忽略，不会入库）：

```bash
cp .env.example .env
```

| 变量 | 必填 | 说明 |
|---|---|---|
| `ANYTHINGLLM_BASE` | 否 | AnythingLLM 地址，默认 `http://localhost:3001` |
| `ANYTHINGLLM_API_KEY` | **是** | API Key；缺失时工具返回明确的配置错误，而不是抛出堆栈 |
| `ANYTHINGLLM_WORKSPACE_SLUG` | 否 | 默认工作区；留空时自动使用第一个工作区 |

## 启动 MCP 服务器

```bash
cd AnythingLLMMCP
python server.py
```

服务器在 `http://127.0.0.1:8765/mcp` 上以 streamable-http 传输运行；`Ctrl+C` 停止。

## 在客户端中使用

MCP 客户端配置（项目根 `.mcp.json` 已包含该条目）：

```json
{
  "mcpServers": {
    "anythingllm": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

使用前先启动 `python server.py`，再在客户端新建会话即可看到下列工具。

## 可用工具

| 工具 | 能力类别 | 参数 | 返回 |
|---|---|---|---|
| `list_workspaces` | 工作区管理 | 无 | 工作区名称、slug、文档数量 |
| `create_workspace` | 工作区管理 | `name` | 新建工作区的名称与 slug |
| `query_workspace` | 对话问答 | `message`、`workspace_slug?` | AI 回答 + 参考来源文件名 |
| `upload_document` | 文档上传/向量化 | `file_path`、`workspace_slug?` | 上传结果与文档标题/位置 |
| `list_workspace_documents` | 文档查询 | `workspace_slug?` | 已向量化文档列表 |

### 调用示例

```text
list_workspaces()
→ {"ok": true, "count": 2, "workspaces": [{"name": "课程知识库", "slug": "course-kb", "documents": 3}]}

query_workspace(message="AnythingLLM 支持哪些文档格式？")
→ {"ok": true, "workspace": "course-kb", "answer": "...", "sources": ["faq.pdf"]}

upload_document(file_path="E:/notes/week7.md")
→ {"ok": true, "workspace": "course-kb", "file": "week7.md", "uploaded": 1}
```

上传成功后 AnythingLLM 会自动切分并向量化，随后可直接用 `query_workspace` 检索到。

## 失败场景与排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `未配置 ANYTHINGLLM_API_KEY` | `.env` 未填 Key | 在 AnythingLLM 生成 Key 并写入 `.env` 后重启 |
| `API Key 无效或缺失（HTTP 401）` | Key 错误/过期 | 重新生成 API Key |
| `无法连接 AnythingLLM（...）` | 服务未启动或端口不对 | 启动 AnythingLLM，核对 `ANYTHINGLLM_BASE` |
| `工作区或接口不存在（HTTP 404）` | slug 错误 | 先调用 `list_workspaces` 查看可用 slug |
| `不支持的文件类型` | 扩展名不在白名单 | 转换为 PDF/TXT/MD/DOCX 等支持格式 |
| `文件过大` | 超过 20 MB | 拆分或压缩后重新上传 |

## 安全说明

- API Key 只从环境变量读取，未写入代码或前端。
- 上传接口限制扩展名白名单与 20 MB 上限，避免误传可执行文件。
- 服务器默认只绑定 `127.0.0.1`，不对公网暴露。
