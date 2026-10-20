# Practice02 — 流式 Agent（Function Calling）

基于 OpenAI SDK v1+（DeepSeek 兼容端点）实现的**流式 Function Calling Agent** 示例，包含两个可独立运行的文件：

| 文件 | 说明 |
| --- | --- |
| `chat2.py` | 基础版：2 个自定义工具（取当前时间、判断闰年）的流式 Agent |
| `chat_file_ops.py` | 进阶版：在 `chat2.py` 架构上扩展到 10 个本地文件操作工具，并带沙箱路径安全校验 |
| `architecture.mmd` | `chat2.py` 的 Mermaid 代码架构图 |

---

## 1. 环境要求

- Python 3.10+（用到了 `str | None` 类型注解）
- `openai` 包

```bash
pip install openai
```

- 运行平台：Windows（`chat2.py` 的 `getDate` 通过 `cmd` 调用系统 `date /t`、`time /t` 命令）

---

## 2. 运行方式

### chat2.py（时间 / 闰年工具）

```bash
python chat2.py
```

脚本启动后会自动跑两个测试用例，然后进入交互式对话：

```
=== 流式 Agent（支持 Function Calling）===
---- 测试用例 1：帮我看看现在几点了 ----
---- 测试用例 2：2999 年是不是闰年？----
you> 
```

### chat_file_ops.py（文件操作工具）

```bash
# 交互模式
python chat_file_ops.py

# 单次非交互模式：执行一条指令后退出
python chat_file_ops.py --prompt "列出当前目录的文件"
```

---

## 3. chat2.py 工具清单

| 工具名 | 参数 | 实现方式 |
| --- | --- | --- |
| `getDate` | 无 | `subprocess` 调用 `cmd`，先 `chcp 65001` 切 UTF-8 代码页，再执行 `date /t` + `time /t`（避免 GBK 解码把中文星期变乱码） |
| `isLeapYear` | `year: integer` | 纯 Python 取模：`(year % 4 == 0 and year % 100 != 0) or year % 400 == 0` |

---

## 4. chat2.py 核心架构

分为 6 层（详见 `architecture.mmd`）：

1. **客户端初始化层** — 构造 `OpenAI` 客户端（`base_url=https://api.deepseek.com`），模型 `deepseek-chat`。
2. **工具契约层** — `TOOLS` 列表，用 JSON Schema 向模型声明工具名、描述与参数结构。
3. **本地工具实现层** — `get_date()` / `is_leap_year()`，通过 `TOOL_MAP`（工具名 → 可调用对象）分发给执行器。
4. **流式解析辅助层**
   - `_init_tool_call()`：初始化单个 `tool_call` 缓冲结构 `{id, index, function:{name, arguments}}`
   - `parse_stream_chunk()`：消费一个流式 chunk，返回文本片段用于打字机输出，同时按 `index` 累积 `tool_calls` 的名称与参数碎片
   - `tool_calls_finished()`：判断所有累积 call 的 `arguments` 是否已闭合（以 `}` 结尾或无参数），完成则返回标准化列表并解析出 `_parsed_args`
5. **Agent 对话循环层** — `agent_chat()` 的 `while True` 循环：
   - **Step 1** 流式请求模型
   - **Step 2** 判定是否有完整工具调用，构造带 `tool_calls` 的 `assistant` 消息
   - **Step 3** 若需调用工具：本地执行 → 打印 `[tool] ...` 日志 → 追加 `role=tool` 消息 → `continue` 回到 Step 1
   - **Step 4** 无工具调用 → 本轮结束，`break`
6. **主入口层** — `main()` 初始化 system prompt，跑两个测试用例后进入交互循环。

### 关键设计点

- **流式工具调用拼接**：模型流式返回的 `tool_calls` 参数是碎片化的，必须按 `index` 归并，再用「`arguments` 以 `}` 结尾」作为完成判据。
- **assistant 消息必须携带 `tool_calls`**：否则后续 `role=tool` 消息无法被模型关联，会报错或语义错乱。
- **`content` 与 `tool_calls` 可并存**：`assistant_msg["content"]` 为空时填 `None`，同时兼容纯文本回复与纯工具调用两种情形。

---

## 5. chat_file_ops.py 扩展说明

在 `chat2.py` 完全相同的流式解析与 Agent 循环架构上，替换/扩展了工具层：

### 沙箱安全（`_validate_path`）

所有工具在执行前统一做路径校验：

- 解析为绝对路径，拒绝空路径
- 拒绝盘根目录（`C:\`、`D:\`、`/`）
- 拒绝父目录穿越：路径必须等于或以 `SANDBOX_ROOT` 为前缀
- 可选的 `must_exist` / `must_be_file` / `must_be_dir` 校验

`SANDBOX_ROOT` 即 `chat_file_ops.py` 所在目录，所有文件操作都不能越出该目录。

### 10 个工具

| 工具名 | 作用 |
| --- | --- |
| `get_cwd` | 返回沙箱根目录绝对路径 |
| `list_dir` | 列出目录下文件/子目录（含大小） |
| `get_file_type` | 返回扩展名、是否纯文本、大小 |
| `read_file` | 读取纯文本文件全文（二进制文件返回错误） |
| `create_file` | 在指定目录创建新文件（已存在则拒绝） |
| `edit_file` | 三模式编辑：`overwrite` / `append` / `replace` |
| `create_dir` | 递归创建目录 |
| `delete_dir` | 递归删除目录（禁止删除沙箱根） |
| `delete_file` | 删除文件 |
| `rename_path` | 同目录改名（禁止跨目录移动） |

### 其他细节

- `_is_text_file()`：读取前 8192 字节，检测是否含 `\x00` 判断文本 / 二进制。
- `create_file` 拒绝含路径分隔符的文件名；`rename_path` 要求新旧路径同目录。
- 提供 `--prompt` 单次运行模式，便于脚本化与测试。
- `SYSTEM_PROMPT` 明确约束：只做自然语言总结，不输出 JSON 或工具名。

---

## 6. 架构图

`architecture.mmd` 为 Mermaid `flowchart` 格式，可直接在 GitHub / VS Code（Mermaid 插件）/ [mermaid.live](https://mermaid.live) 中渲染。内容包括：

- 6 个分层子图（客户端 / 工具契约 / 工具实现 / 流式解析 / Agent 循环 / 主入口）
- 跨层依赖边
- 运行时 `messages[]` 数据流（user → assistant → tool → 回传模型）

---

## 7. 注意

- 代码中 `api_key` 为硬编码，**请勿把真实密钥提交到公开仓库**，建议改为从环境变量读取（如 `os.getenv("DEEPSEEK_API_KEY")`）。
- `delete_dir` / `delete_file` 为危险操作，虽然已做沙箱限制，使用前仍建议确认路径。
