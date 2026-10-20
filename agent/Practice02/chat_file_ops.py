"""
chat_file_ops.py
支持本地文件操作 Function Calling 的流式 Agent（基于 chat2.py 架构）。

10 个工具：
  1. get_cwd        — 获取当前工作目录
  2. list_dir       — 列出指定目录下所有文件和子目录
  3. get_file_type  — 获取指定文件的文件类型
  4. read_file      — 获取指定纯文本文件的内容
  5. create_file    — 根据目录和文件名创建新文件
  6. edit_file      — 编辑指定文件内容（覆盖/追加/替换）
  7. create_dir     — 创建新目录
  8. delete_dir     — 删除目录（支持非空）
  9. delete_file    — 删除文件
  10. rename_path   — 重命名文件或目录

运行：
  python chat_file_ops.py                  # 交互模式
  python chat_file_ops.py --prompt "xxx"   # 单次非交互模式
"""

import argparse
import json
import os
import shutil

from openai import OpenAI

# ========== 1. 初始化客户端 ==========
client = OpenAI(
    api_key="sk-a5aaef985e1b4e2e9dac825af5ed7e32",
    base_url="https://api.deepseek.com",
)
MODEL = "deepseek-chat"

# 沙箱根目录：所有文件操作被限制在此目录下
SANDBOX_ROOT = os.path.abspath(os.path.dirname(__file__))

# ========== 2. 路径安全校验 ==========


def _validate_path(raw_path: str, must_exist: bool = False,
                   must_be_file: bool = False, must_be_dir: bool = False) -> str:
    """
    统一路径校验：解析绝对路径、拒绝空路径/根目录/父目录穿越、限制在沙箱内。
    返回解析后的绝对路径；校验失败时抛出 ValueError。
    """
    if not raw_path or not raw_path.strip():
        raise ValueError("路径不能为空")

    # 解析为绝对路径
    abs_path = os.path.abspath(os.path.join(SANDBOX_ROOT, raw_path)) \
        if not os.path.isabs(raw_path) else os.path.abspath(raw_path)

    # 拒绝根目录（防止误删盘根）
    if abs_path in (os.path.abspath("/"), os.path.abspath("\\"),
                    os.path.abspath("C:\\"), os.path.abspath("D:\\")):
        raise ValueError(f"禁止操作根目录: {abs_path}")

    # 拒绝父目录穿越
    if not (abs_path == SANDBOX_ROOT or abs_path.startswith(SANDBOX_ROOT + os.sep)):
        raise ValueError(f"路径超出沙箱范围（禁止父目录穿越）: {raw_path} -> {abs_path}")

    # 可选：存在性 / 类型校验
    if must_exist and not os.path.exists(abs_path):
        raise ValueError(f"路径不存在: {abs_path}")
    if must_be_file:
        if not os.path.exists(abs_path):
            raise ValueError(f"文件不存在: {abs_path}")
        if not os.path.isfile(abs_path):
            raise ValueError(f"路径不是文件: {abs_path}")
    if must_be_dir:
        if not os.path.exists(abs_path):
            raise ValueError(f"目录不存在: {abs_path}")
        if not os.path.isdir(abs_path):
            raise ValueError(f"路径不是目录: {abs_path}")

    return abs_path


def _is_text_file(file_path: str) -> bool:
    """通过检测前 8192 字节是否含 \\x00 来判断是否为纯文本文件。"""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" not in chunk
    except OSError:
        return False


# ========== 3. Tools JSON Schema ==========
TOOLS = [
    # --- 3.1 get_cwd ---
    {
        "type": "function",
        "function": {
            "name": "get_cwd",
            "description": "获取当前工作目录（沙箱根目录的绝对路径）",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    # --- 3.2 list_dir ---
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "列出指定目录下的所有文件和子目录（仅允许沙箱范围内）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "目录路径，可传相对路径（相对于沙箱根目录）或绝对路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.3 get_file_type ---
    {
        "type": "function",
        "function": {
            "name": "get_file_type",
            "description": "获取指定文件的文件类型（扩展名 / 是目录还是文件）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.4 read_file ---
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取指定纯文本文件的完整内容（二进制文件会返回错误）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文本文件路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.5 create_file ---
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "在指定目录下创建一个新的纯文本文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目标目录路径"},
                    "filename": {"type": "string", "description": "新文件名"},
                    "content": {"type": "string", "description": "文件初始内容（可为空字符串）"}
                },
                "required": ["dir", "filename", "content"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.6 edit_file ---
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "编辑指定纯文本文件内容。mode=overwrite 覆盖整个文件；mode=append 追加到末尾；mode=replace 把 old 替换为 new",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要编辑的文件路径"},
                    "mode": {"type": "string", "enum": ["overwrite", "append", "replace"],
                             "description": "编辑模式：overwrite 覆盖 / append 追加 / replace 替换指定文本"},
                    "content": {"type": "string", "description": "overwrite 时为新内容；append 时为追加内容；replace 时忽略"},
                    "old": {"type": "string", "description": "replace 时要被替换的原文本"},
                    "new": {"type": "string", "description": "replace 时替换成的新文本"}
                },
                "required": ["path", "mode"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.7 create_dir ---
    {
        "type": "function",
        "function": {
            "name": "create_dir",
            "description": "创建新目录（支持递归创建父目录）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "新目录路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.8 delete_dir ---
    {
        "type": "function",
        "function": {
            "name": "delete_dir",
            "description": "删除目录（支持非空目录递归删除）。危险操作，请谨慎使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的目录路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.9 delete_file ---
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "删除指定文件。危险操作。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要删除的文件路径"}
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    # --- 3.10 rename_path ---
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "重命名文件或目录（也可用于跨目录移动，但目标必须仍在沙箱内）",
            "parameters": {
                "type": "object",
                "properties": {
                    "old_path": {"type": "string", "description": "原路径"},
                    "new_path": {"type": "string", "description": "新路径（必须与原路径在同一目录下，即仅改名不移动）"}
                },
                "required": ["old_path", "new_path"],
                "additionalProperties": False,
            },
        },
    },
]

# ========== 4. 本地工具实现 ==========


def tool_get_cwd(_args: dict) -> str:
    return SANDBOX_ROOT


def tool_list_dir(args: dict) -> str:
    path = _validate_path(args.get("path", "."), must_exist=True, must_be_dir=True)
    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        if os.path.isdir(full):
            entries.append(f"[DIR]  {name}")
        else:
            size = os.path.getsize(full)
            entries.append(f"[FILE] {name} ({size} bytes)")
    header = f"目录 {path} 下共 {len(entries)} 项:"
    return header + "\n" + "\n".join(entries) if entries else header + "\n(空)"


def tool_get_file_type(args: dict) -> str:
    path = _validate_path(args.get("path", "."), must_exist=True)
    if os.path.isdir(path):
        return f"{path} 是目录"
    ext = os.path.splitext(path)[1].lower() or "(无扩展名)"
    size = os.path.getsize(path)
    text_flag = "纯文本" if _is_text_file(path) else "二进制"
    return f"{path}\n  扩展名: {ext}\n  类型: {text_flag}\n  大小: {size} bytes"


def tool_read_file(args: dict) -> str:
    path = _validate_path(args.get("path", ""), must_exist=True, must_be_file=True)
    if not _is_text_file(path):
        return f"错误: {path} 是二进制文件，不支持读取内容"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as e:
        return f"读取失败: {e}"
    return f"===== {path} =====\n{content}\n===== 文件结束 ====="


def tool_create_file(args: dict) -> str:
    dir_path = _validate_path(args.get("dir", ""), must_exist=True, must_be_dir=True)
    filename = args.get("filename", "").strip()
    if not filename:
        return "错误: filename 不能为空"
    # 拒绝文件名中的路径分隔符
    if os.sep in filename or "/" in filename or "\\" in filename:
        return f"错误: filename 不能含路径分隔符: {filename}"
    content = args.get("content", "") or ""
    full_path = os.path.join(dir_path, filename)
    if os.path.exists(full_path):
        return f"错误: 文件已存在 {full_path}（如需覆盖请用 edit_file 的 overwrite 模式）"
    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return f"创建失败: {e}"
    return f"已创建文件 {full_path}，大小 {len(content.encode('utf-8'))} bytes"


def tool_edit_file(args: dict) -> str:
    path = _validate_path(args.get("path", ""), must_exist=True, must_be_file=True)
    mode = args.get("mode", "")
    if mode not in ("overwrite", "append", "replace"):
        return f"错误: mode 必须是 overwrite/append/replace，收到 {mode!r}"
    if not _is_text_file(path):
        return f"错误: {path} 是二进制文件，不支持编辑"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            original = f.read()
        if mode == "overwrite":
            new_content = args.get("content", "") or ""
        elif mode == "append":
            new_content = original + (args.get("content", "") or "")
        else:  # replace
            old = args.get("old", "") or ""
            new = args.get("new", "") or ""
            if old not in original:
                return f"错误: 原文本在文件中未找到，无法替换"
            new_content = original.replace(old, new)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        return f"编辑失败: {e}"
    size = len(new_content.encode("utf-8"))
    return f"已编辑 {path}（mode={mode}），新大小 {size} bytes"


def tool_create_dir(args: dict) -> str:
    path = _validate_path(args.get("path", ""))
    if os.path.exists(path):
        return f"错误: 路径已存在 {path}"
    try:
        os.makedirs(path, exist_ok=False)
    except OSError as e:
        return f"创建目录失败: {e}"
    return f"已创建目录 {path}"


def tool_delete_dir(args: dict) -> str:
    path = _validate_path(args.get("path", ""), must_exist=True, must_be_dir=True)
    # 拒绝删除沙箱根目录本身
    if path == SANDBOX_ROOT:
        return "错误: 禁止删除沙箱根目录"
    try:
        shutil.rmtree(path)
    except OSError as e:
        return f"删除目录失败: {e}"
    return f"已删除目录 {path}（含所有子项）"


def tool_delete_file(args: dict) -> str:
    path = _validate_path(args.get("path", ""), must_exist=True, must_be_file=True)
    try:
        os.remove(path)
    except OSError as e:
        return f"删除文件失败: {e}"
    return f"已删除文件 {path}"


def tool_rename_path(args: dict) -> str:
    old_path = _validate_path(args.get("old_path", ""), must_exist=True)
    new_path_raw = args.get("new_path", "").strip()
    if not new_path_raw:
        return "错误: new_path 不能为空"
    # new_path 也必须在沙箱内
    new_path = _validate_path(new_path_raw)
    # 仅允许同目录改名（防止跨目录移动绕过校验）
    if os.path.dirname(old_path) != os.path.dirname(new_path):
        return "错误: 仅支持同目录改名，不支持跨目录移动"
    if os.path.exists(new_path):
        return f"错误: 目标路径已存在 {new_path}"
    try:
        os.rename(old_path, new_path)
    except OSError as e:
        return f"重命名失败: {e}"
    what = "目录" if os.path.isdir(new_path) else "文件"
    return f"已重命名{what}: {old_path} -> {new_path}"


# 工具名 -> 可调用对象
TOOL_MAP = {
    "get_cwd": tool_get_cwd,
    "list_dir": tool_list_dir,
    "get_file_type": tool_get_file_type,
    "read_file": tool_read_file,
    "create_file": tool_create_file,
    "edit_file": tool_edit_file,
    "create_dir": tool_create_dir,
    "delete_dir": tool_delete_dir,
    "delete_file": tool_delete_file,
    "rename_path": tool_rename_path,
}


# ========== 5. 流式解析 & Agent 循环（复用 chat2.py 架构）==========


def _init_tool_call(call_id, call_index, function_name=""):
    return {
        "id": call_id,
        "index": call_index,
        "function": {"name": function_name, "arguments": ""},
    }


def parse_stream_chunk(chunk, tool_calls_accum: dict) -> str | None:
    content_text = None
    if not chunk.choices:
        return content_text
    delta = chunk.choices[0].delta
    if delta.content:
        content_text = delta.content
    if delta.tool_calls:
        for tc in delta.tool_calls:
            idx = tc.index
            if idx not in tool_calls_accum:
                tool_calls_accum[idx] = _init_tool_call(
                    call_id=tc.id or f"call_{idx}",
                    call_index=idx,
                    function_name=tc.function.name or "",
                )
            else:
                if tc.function.name and not tool_calls_accum[idx]["function"]["name"]:
                    tool_calls_accum[idx]["function"]["name"] = tc.function.name
                if tc.function.arguments:
                    tool_calls_accum[idx]["function"]["arguments"] += tc.function.arguments
    return content_text


def tool_calls_finished(tool_calls_accum: dict) -> list | None:
    if not tool_calls_accum:
        return None
    for call in tool_calls_accum.values():
        args = call["function"]["arguments"].strip()
        if args and not args.endswith("}"):
            return None
    result = []
    for call in tool_calls_accum.values():
        args_str = call["function"]["arguments"].strip()
        args_str = args_str if args_str else "{}"
        try:
            parsed_args = json.loads(args_str)
        except json.JSONDecodeError:
            parsed_args = {}
        result.append({
            "id": call["id"],
            "type": "function",
            "function": {
                "name": call["function"]["name"],
                "arguments": args_str,
            },
            "_parsed_args": parsed_args,
        })
    return result


def agent_chat(user_input: str, messages: list) -> None:
    messages.append({"role": "user", "content": user_input})

    while True:
        tool_calls_accum: dict = {}
        assistant_content_buf: list = []

        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            stream=True,
        )

        print("ai> ", end="", flush=True)

        for chunk in stream:
            text = parse_stream_chunk(chunk, tool_calls_accum)
            if text:
                assistant_content_buf.append(text)
                print(text, end="", flush=True)

        finished_calls = tool_calls_finished(tool_calls_accum)

        assistant_msg = {
            "role": "assistant",
            "content": "".join(assistant_content_buf) or None,
        }
        if finished_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {
                        "name": c["function"]["name"],
                        "arguments": c["function"]["arguments"],
                    },
                }
                for c in finished_calls
            ]
        messages.append(assistant_msg)

        if finished_calls:
            print()
            for call in finished_calls:
                fname = call["function"]["name"]
                parsed_args = call["_parsed_args"]
                print(f"  [tool] {fname}({parsed_args}) => ", end="", flush=True)
                try:
                    result = TOOL_MAP[fname](parsed_args)
                except Exception as e:
                    result = f"工具执行出错: {e}"
                print(result)
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": str(result),
                })
            continue

        print()
        break


# ========== 6. 主入口 ==========


SYSTEM_PROMPT = (
    "你是一个可以调用本地文件操作工具的智能助手。"
    "当用户需要查看/操作文件时，调用对应的工具；"
    "工具结果出来后请直接给出自然语言总结，不要输出 JSON 或工具名。"
    "所有文件操作被限制在项目目录内，不能访问该目录之外的路径。"
)


def main():
    parser = argparse.ArgumentParser(description="流式文件操作 Agent")
    parser.add_argument("--prompt", type=str, default=None,
                        help="单次运行模式：直接执行这条指令后退出")
    args = parser.parse_args()

    messages: list = [{"role": "system", "content": SYSTEM_PROMPT}]

    print("=== 流式 Agent（10 个本地文件操作工具）===")
    print(f"沙箱根目录: {SANDBOX_ROOT}")
    print("Ctrl+C 退出\n")

    # --- 非交互单次模式 ---
    if args.prompt:
        print(f"[单次模式] you> {args.prompt}")
        agent_chat(args.prompt, messages)
        return

    # --- 交互循环 ---
    try:
        while True:
            try:
                user_input = input("you> ")
            except EOFError:
                print("\nbye")
                break
            if not user_input.strip():
                continue
            agent_chat(user_input, messages)
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
