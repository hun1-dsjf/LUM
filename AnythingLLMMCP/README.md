# AnythingLLM MCP Server

通过 MCP 协议访问本机 AnythingLLM 的 HTTP 服务，支持向第一个工作区提问并获取 AI 回答。

## 前置条件

- Python 3.13+
- 本机运行 AnythingLLM（默认 `http://localhost:3001`）
- 已配置 AnythingLLM API Key

## 安装依赖

```bash
cd anythingllm-mcp
pip install -r requirements.txt
```

## 配置

编辑 `.env` 文件：

```
ANYTHINGLLM_BASE=http://localhost:3001
ANYTHINGLLM_API_KEY=你的API Key
ANYTHINGLLM_WORKSPACE_SLUG=   # 留空则自动使用第一个工作区
```

## 启动 MCP 服务器

```bash
cd anythingllm-mcp
python server.py
```

服务器将在 `http://127.0.0.1:8765/mcp` 上运行（streamable-http 传输）。

## 停止 MCP 服务器

在运行 server.py 的终端窗口中按 `Ctrl+C` 即可停止。

## 在 Trae 中使用

项目根目录已配置 `.mcp.json`，Trae 会自动发现 `anythingllm` MCP 服务器。

**使用流程：**
1. 先在终端中启动 MCP 服务器（`python server.py`）
2. 在 Trae 中打开新聊天会话，即可使用 `query_workspace` 工具

## 可用工具

### query_workspace

向 AnythingLLM 第一个工作区提问，返回 AI 回答。

- **参数**：`message`（字符串）— 要向工作区提出的问题
- **返回**：AI 回答文本，附带参考来源文件名
