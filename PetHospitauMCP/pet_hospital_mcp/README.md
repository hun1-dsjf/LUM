# Pet Hospital MCP

将 [Go 宠物医院 REST API](../) 的能力暴露给 AI Agent 的 MCP 服务。

- **语言 / 运行时**: Python 3.11+
- **MCP Python SDK**: `mcp==2.0.0`（官方 `mcp.server.MCPServer`，非旧版 `FastMCP`）
- **MCP 协议版本**: `2026-07-28`
- **传输模型**: 无状态 Streamable HTTP（`stateless_http=True`, `json_response=True`）
  - 不发送旧协议的 `initialize`
  - 不要求或返回 `Mcp-Session-Id`
  - 不维护会话存储 / 会话过期 / SSE 恢复
- **后端**: 仅通过 HTTP 调用 Go REST API，默认 `http://127.0.0.1:8080`，不修改 Go 服务

> 本仓库**未实现阶段二的工具**。当前仅提供一个工具：`list_pets`。详见文末「范围声明」。

---

## 目录结构

```text
pet_hospital_mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py          # 版本 + 协议/SDK 常量
│       ├── __main__.py          # python -m pet_hospital_mcp 入口
│       ├── config.py            # 环境变量配置
│       ├── server.py            # MCPServer 装配 + /health + /mcp ASGI 应用
│       ├── rest_client.py       # httpx 调用 Go REST API（超时 + 有限重试 + 错误映射）
│       ├── errors.py            # 统一错误结构 + 错误码 + BackendError
│       ├── logging_config.py    # JSON 日志 + 敏感字段递归脱敏
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py     # list_pets 工具（输入/输出模型 + 处理器 + 注册）
└── tests/
    ├── conftest.py              # 共享 fixture + MCP 请求/响应助手
    ├── test_models.py
    ├── test_rest_client.py
    ├── test_list_pets_tool.py
    └── test_server.py
```

后续阶段新增工具时，只需在 `tools/` 增加模块并复用 `rest_client`、`errors`、`logging_config` 约定。

---

## 前置条件：先启动 Go REST API

MCP 服务依赖 Go 宠物医院 REST API，**必须先启动它**。在仓库根目录执行：

```bash
# 方式一：直接运行源码（默认监听 127.0.0.1:8080）
go run .

# 方式二：用 Make
make run

# 方式三：构建后运行（带测试数据库）
make dist && cd dist && ./pethospital(.exe)
```

Go 服务默认监听 `127.0.0.1:8080`，提供 `GET /api/v1/pets` 等接口。可用：

```bash
curl http://127.0.0.1:8080/api/v1/pets?page=1\&pageSize=5
```

确认返回 `{"code":200,"message":"ok","data":{...},"time":"..."}` 即就绪。

---

## 安装与启动

```bash
cd pet_hospital_mcp

# 1. 创建虚拟环境
python -m venv .venv
#    Windows:
.venv\Scripts\activate
#    macOS/Linux:
source .venv/bin/activate

# 2. 以可编辑模式安装（含开发依赖）
pip install -e ".[dev]"

# 3. 启动 MCP 服务（默认 127.0.0.1:8000）
python -m pet_hospital_mcp
# 或使用控制台脚本
pet-hospital-mcp
# 或用 uvicorn 直接跑 ASGI app
uvicorn pet_hospital_mcp.server:app --host 127.0.0.1 --port 8000
```

---

## 配置

全部通过环境变量配置，均有本地教学场景的安全默认值（不配置也能跑）：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MCP_HOST` | `127.0.0.1` | MCP 服务监听地址（默认仅本地） |
| `MCP_PORT` | `8000` | MCP 服务监听端口 |
| `MCP_HTTP_PATH` | `/mcp` | MCP Streamable HTTP 端点路径 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API 基址 |
| `PET_HOSPITAL_TIMEOUT` | `10` | 调用 Go API 的单次超时（秒） |
| `PET_HOSPITAL_RETRIES` | `1` | 超时/5xx 的重试次数（总尝试 = retries + 1） |
| `MCP_LOG_LEVEL` | `info` | uvicorn 日志级别 |

示例：

```bash
MCP_HOST=127.0.0.1 MCP_PORT=8000 \
PET_HOSPITAL_BASE_URL=http://127.0.0.1:8080 \
python -m pet_hospital_mcp
```

---

## 端点

| 路径 | 方法 | 说明 |
| --- | --- | --- |
| `/mcp` | POST | MCP Streamable HTTP 端点（无状态，2026-07-28） |
| `/health` | GET | 健康检查（无需鉴权，返回服务元信息） |
| `/favicon.ico` | GET | 浏览器图标占位 |

### `/health` 示例

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "status": "ok",
  "service": "Pet Hospital MCP",
  "version": "0.1.0",
  "mcp_sdk_version": "2.0.0",
  "mcp_protocol_version": "2026-07-28",
  "transport": "streamable-http (stateless)",
  "mcp_endpoint": "http://127.0.0.1:8000/mcp",
  "backend_base_url": "http://127.0.0.1:8080"
}
```

---

## 验证无状态 MCP 连接（MCP Inspector / SDK 2.x 客户端）

### 方式 A：MCP Inspector

```bash
npx @modelcontextprotocol/inspector \
  --transport http \
  --url http://127.0.0.1:8000/mcp \
  --protocol-version 2026-07-28
```

Inspector 会自动执行 `server/discover`、`tools/list`，并可手动调用 `list_pets`。

### 方式 B：直接 HTTP（2026-07-28 请求信封）

2026-07-28 协议要求：每个请求的 `params._meta` 携带带命名空间的协议版本与客户端能力信封，且 HTTP 头需带 `MCP-Protocol-Version`、`Mcp-Method`（以及 `tools/call` 的 `Mcp-Name`）。

**1. 发现（替代旧 `initialize`）**

```bash
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -H "Mcp-Method: server/discover" \
  -d '{
    "jsonrpc":"2.0","id":1,"method":"server/discover",
    "params":{"_meta":{
      "io.modelcontextprotocol/protocolVersion":"2026-07-28",
      "io.modelcontextprotocol/clientCapabilities":{},
      "io.modelcontextprotocol/clientInfo":{"name":"curl","version":"0.0"}
    }}
  }'
```

> 响应**不含** `Mcp-Session-Id` 头（无状态）。

**2. 列出工具**

```bash
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -H "Mcp-Method: tools/list" \
  -d '{
    "jsonrpc":"2.0","id":2,"method":"tools/list",
    "params":{"_meta":{
      "io.modelcontextprotocol/protocolVersion":"2026-07-28",
      "io.modelcontextprotocol/clientCapabilities":{}
    }}
  }'
```

**3. 调用 `list_pets`**

```bash
curl -s -X POST http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "MCP-Protocol-Version: 2026-07-28" \
  -H "Mcp-Method: tools/call" \
  -H "Mcp-Name: list_pets" \
  -d '{
    "jsonrpc":"2.0","id":3,"method":"tools/call",
    "params":{
      "name":"list_pets",
      "arguments":{"params":{"page":1,"pageSize":5,"species":"犬","sortBy":"totalCost","order":"desc"}},
      "_meta":{
        "io.modelcontextprotocol/protocolVersion":"2026-07-28",
        "io.modelcontextprotocol/clientCapabilities":{}
      }
    }
  }'
```

成功返回的 `result.content[0].text` 是 `ListPetsResult` 的 JSON：

```json
{
  "items": [ {"id":"PET-000001","name":"旺财","species":"犬", ...} ],
  "total": 5,
  "page": 1,
  "pageSize": 5,
  "totalPages": 200,
  "totalCost": 1900.0
}
```

> 注意：工具签名是 `list_pets(params: ListPetsInput)`，因此 14 个查询参数嵌套在 `arguments.params` 下。`ListPetsInput` 配置了 `extra="forbid"`，会拒绝未知字段。

---

## `list_pets` 工具

适配 Go `GET /api/v1/pets`，支持且仅支持以下查询参数（全部可选）：

| 参数 | 类型 | 约束 |
| --- | --- | --- |
| `q` | str | 全文检索 |
| `name` | str | 宠物姓名模糊匹配 |
| `ownerName` | str | 主人姓名模糊匹配 |
| `ownerPhone` | str | 主人电话模糊匹配 |
| `species` | str | 精确匹配；允许值：犬/猫/兔/鸟/仓鼠/爬宠/其他 |
| `doctor` | str | 医生模糊匹配 |
| `disease` | str | 疾病模糊匹配 |
| `status` | str | 精确匹配；允许值：待就诊/就诊中/住院中/已康复/慢性病随访 |
| `min` | number | 总花费下限（含），非负，不能为 NaN/Infinity |
| `max` | number | 总花费上限（含），非负，且 >= min |
| `sortBy` | str | id/name/ownerName/species/doctor/disease/status/totalCost/visitCount/createdAt/updatedAt |
| `order` | str | asc/desc |
| `page` | int | 页码，从 1 开始（默认 1） |
| `pageSize` | int | 每页条数，1-500（默认 20） |

### 错误结构

所有无效输入与上游异常统一返回：

```json
{"error":{"code":"ERROR_CODE","message":"可读错误信息","details":{}}}
```

错误码：`VALIDATION_ERROR` / `BACKEND_TIMEOUT` / `BACKEND_UNAVAILABLE` / `BACKEND_API_ERROR` / `BACKEND_INVALID_RESPONSE` / `INTERNAL_ERROR`。

工具调用失败按 SDK 2.x 规定以 `isError=true` 标记（`CallToolResult.isError`）。HTTPX / Pydantic / SDK / Python 堆栈不会原样暴露给 MCP 客户端。

---

## 单元测试

测试使用 `pytest` + `pytest-asyncio`，后端通过 `httpx.MockTransport` 完全模拟，**不访问真实 Go 服务**。

```bash
cd pet_hospital_mcp
pytest -q
```

预期结果：**全部通过**。

覆盖：

1. 正常调用 — 请求路径与全部过滤/排序/分页参数正确转发；
2. 输入参数校验失败（species/status/sortBy/order/page/pageSize/min/max/NaN/Infinity/未知字段）；
3. Go REST API 返回 4xx / 5xx（含重试与恢复）；
4. 超时和连接异常（含重试）；
5. 后端返回非法 JSON 或不符合数据模型；
6. MCP 工具注册、工具名与 JSON Schema；
7. SDK 2.x 无状态连接流程：`/health` + `server/discover` + `tools/list` + `tools/call`（成功与校验失败），且无 `Mcp-Session-Id`。

---

## 范围声明

本服务**未实现阶段二的工具**（如 `get_pet` / `create_pet` / `update_pet` 等）。当前仅提供 `list_pets` 一个工具。新增工具的扩展指引见 [UPGRADE_PROMPT.md](./UPGRADE_PROMPT.md)。
