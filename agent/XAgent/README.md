# XAgent —— 可插拔 UI 的流式 Function Calling Agent

基于 `agent/Practice02/chat_file_ops.py` 重构而来，实现 **Core 与 UI 彻底分离**的架构。

## 架构

```
XAgent/
├── main.py                 # 入口：CLI 参数解析 + 模式切换
├── requirements.txt
├── .env.example
├── config/                 # 配置层（纯数据，无业务逻辑）
│   ├── settings.py         # LLMConfig + SANDBOX_ROOT + load_dotenv
│   └── __init__.py
├── core/                   # 核心引擎（零 print / 零 UI 依赖）
│   ├── agent.py            # Agent 类 + EventCallback 协议 + 流式解析
│   └── __init__.py
├── tools/                  # 工具层（可独立测试、独立替换）
│   ├── file_ops.py         # 10 个本地文件操作工具 + 沙箱校验
│   └── __init__.py
└── ui/                     # UI 层（可替换：Textual / FastAPI / PyQt）
    ├── tui.py              # Textual TUI，实现 EventCallback 协议
    └── __init__.py
```

### 关键设计：Core → UI 的事件回调协议

`core/agent.py` 定义了一个 `EventCallback` Protocol，UI 层实现此协议即可：

| 回调方法 | 触发时机 | 典型 UI 行为 |
|---|---|---|
| `on_text_delta(str)` | 流式收到一段文本增量 | 打字机追加显示 |
| `on_tool_start(name, args)` | 模型决定调用工具 | 显示"正在执行 xxx..." |
| `on_tool_result(name, args, result)` | 工具执行完毕 | 显示工具返回值 |
| `on_ai_done(full_text)` | AI 本轮回复结束 | 换行、恢复输入 |

Core 层 **绝对不 print、不 import 任何 UI 库**。未来接 Web 版只需写一个 FastAPI 的 Callback 实现（把事件推到 WebSocket），接桌面版只需写一个 PyQt 的 Callback 实现。

### 异步流式

- 使用 `AsyncOpenAI` + `async for` 消费流式响应，不阻塞 Textual 事件循环
- 避免了同步 `stream=True` 在 TUI 中全程冻结的经典问题

### 沙箱安全

所有文件操作被限制在 `XAgent/` 目录下（`SANDBOX_ROOT`），拒绝：
- 空路径、盘根目录（`C:\`）
- 父目录穿越（`..`）
- 沙箱根目录删除

## 安装

```bash
cd agent/XAgent
pip install -r requirements.txt
cp .env.example .env   # 填入真实 API_KEY / BASE_URL / MODEL
```

## 运行

```bash
# Textual TUI 交互模式（推荐）
python main.py

# 单次非交互模式（方便脚本化/测试）
python main.py --prompt "列出当前目录的文件"
```

TUI 中输入 `quit` / `exit` / `bye` 或按 `Esc` / `Ctrl+C` 退出。

## 工具清单（10 个）

| 工具 | 说明 |
|---|---|
| `get_cwd` | 沙箱根目录 |
| `list_dir` | 列出目录内容 |
| `get_file_type` | 文件类型/大小/文本或二进制 |
| `read_file` | 读纯文本文件 |
| `create_file` | 创建新文件（禁止路径穿越） |
| `edit_file` | overwrite / append / replace 三模式 |
| `create_dir` | 递归创建目录 |
| `delete_dir` | 递归删除非空目录（禁止删根） |
| `delete_file` | 删除文件 |
| `rename_path` | 同目录改名（禁止跨目录） |
