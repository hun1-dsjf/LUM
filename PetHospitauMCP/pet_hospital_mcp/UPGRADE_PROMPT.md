# UPGRADE_PROMPT — 阶段二扩展指引

> 本文件不是当前已实现的功能说明，而是给「阶段二」开发者（人或 AI）的扩展约定。
> 当前的 `pet_hospital_mcp/` 服务**只实现了 `list_pets` 一个工具**，其余 Go REST API 端点尚未适配。
> 阶段二的目标是在不破坏现有契约的前提下，按相同约定新增工具。

---

## 你是一位 MCP + Python 专家。请基于现有 `pet_hospital_mcp/` 服务扩展阶段二工具。

### 不可破坏的既有契约（必须遵守）

1. **SDK / 协议**：使用官方 `mcp==2.0.0` 的 `MCPServer`，协议 `2026-07-28`，无状态 Streamable HTTP。**不得**引入 `FastMCP`、旧 `initialize`、`Mcp-Session-Id`、会话存储。
2. **后端边界**：只通过 `pet_hospital_mcp.rest_client.PetHospitalClient` 调用 Go REST API，**不得**修改 Go 服务，**不得**绕过 REST 客户端直接 `httpx` 请求。
3. **统一错误结构**：所有失败返回 `{"error":{"code","message","details"}}`，错误码沿用 `errors.py` 中的常量；新增错误码需加到 `errors.py` 并补文档。不把 HTTPX / Pydantic / SDK / Python 堆栈暴露给 MCP 客户端。
4. **工具失败标记**：按 SDK 2.x，失败以 `CallToolResult.isError=true` 标记（通过 `tools/list_pets.py` 中的 `_tool_error` 桥接模式：`raise ToolError(unified_error_json)`，SDK 会包装为 `isError=true` 的 content）。
5. **输入严格校验**：Pydantic 模型 `extra="forbid"`；枚举值必须对齐 Go 真实允许值；范围/NaN/Infinity/min<=max 在处理器 body 内校验并抛 `BackendError(VALIDATION_ERROR)`，不要依赖 SDK 的校验错误格式。
6. **日志**：复用 `logging_config.get_logger`；JSON 日志含 `timestamp/tool_name/params/status/duration_ms`；`ownerPhone`/`ownerAddr`/`chipNo` 及其 snake_case 写法递归脱敏（`logging_config.redact` 已覆盖）。
7. **配置**：新增配置走 `config.py` 环境变量，保留 localhost-only 默认值。

### 扩展约定

新增一个工具的步骤：

1. 在 `src/pet_hospital_mcp/tools/` 下新增模块，例如 `get_pet.py`。
2. 在模块内定义：
   - `ListPetsInput` 风格的 Pydantic 输入模型（`extra="forbid"`，字段对齐 Go API 查询/路径/体参数）；
   - 输出模型（`extra="allow"`，容忍 Go 的 `records`/`charges` 可为 `null`）；
   - `_validate_input(params)` 语义校验；
   - `async def <tool_name>(params: <InputModel>) -> <OutputModel>` 处理器，结构与 `list_pets` 一致：`try` → 校验 → 调 `PetHospitalClient` → 校验上游 `data` → 返回；`except BackendError` → `raise _tool_error(exc.to_json())`；`except Exception` → `INTERNAL_ERROR`；`finally` 记日志。
   - `register(mcp_server)`：`mcp_server.tool(name="<snake_case>")(handler)`。
3. 在 `tools/__init__.py` 导出并 re-export `register_<tool>`。
4. 在 `rest_client.py` 给 `PetHospitalClient` 新增对应方法（调用 Go API 的其它端点），复用 `_get_data` / 解析 / 重试 / 错误映射逻辑。**不得**为每个端点复制重试逻辑——抽公共方法。
5. 在 `server.py` 的 `create_mcp()` 中调用新 `register_*`。
6. 在 `tests/` 新增 `test_<tool>.py`，用 `httpx.MockTransport` 模拟后端，覆盖：正常调用 + 参数转发、校验失败、4xx/5xx、超时/连接异常、非法 JSON/schema 不符。**禁止访问真实 Go 服务。**
7. 运行 `cd pet_hospital_mcp && pytest -q` 必须全绿。

### Go REST API 待适配端点（阶段二候选，需先阅读仓库根目录的 Go 代码确认真实签名）

> 以下是候选清单；**实现前必须先读 `internal/api/api.go` 确认真实路径、方法、参数与响应结构**，不要照此清单臆测。

- `GET /api/v1/pets/{id}` — 取单个宠物档案（含病历/消费明细）
- `POST /api/v1/pets` — 新建宠物档案
- `PUT /api/v1/pets/{id}` — 更新宠物档案
- `DELETE /api/v1/pets/{id}` — 删除宠物档案
- `POST /api/v1/pets/{id}/records` — 新增病历
- `GET /api/v1/meta` — 元信息（species/status 等允许值来源，校验枚举时对齐它）
- 统计 / 聚合类端点（如有）

### 写工具时的关键提醒

- 工具名一律 `snake_case`，不新增适配器私有业务参数。
- 写操作（POST/PUT/DELETE）要明确是否幂等、是否需要确认；教学场景可不实现鉴权，但**不得**降低输入校验强度。
- `PetItem` / `ListPetsResult` 已 `extra="allow"`，新增字段可复用；若 Go 响应结构差异大，新增独立输出模型。
- `server/discover` 和 `/health` 由 `server.py` 统一维护，**不要**在新工具模块里注册路由。
- 测试中复用 `tests/conftest.py` 的 `backend_handler_factory` / `captured_requests` / `install_backend` / `fresh_app` / `mcp_session` / `mcp_call` 助手，不要重复造轮子。

### 验收

- `cd pet_hospital_mcp && pytest -q` 全绿；
- `tools/list` 能发现新工具，JSON Schema 含其参数且 `additionalProperties: false`；
- `tools/call` 新工具成功返回对应 Go `data`；失败返回统一错误结构且 `isError=true`；
- 无 `Mcp-Session-Id`、无旧 `initialize`，仍是无状态 Streamable HTTP。
