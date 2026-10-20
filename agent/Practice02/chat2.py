"""
chat-stream-tool-getDate.py
支持 Function Calling 的流式 Agent 脚本（OpenAI SDK v1+ / DeepSeek 兼容端点）。

两个自定义工具：
  1. getDate     —— 通过 subprocess 调用 Windows 系统 date/time 命令获取当前时间
  2. isLeapYear  —— 纯 Python 取模计算某年份是否闰年

运行：python chat-stream-tool-getDate.py
"""

import json
import subprocess

from openai import OpenAI

# ========== 1. 初始化客户端 ==========
# 复用 Practice01 里的配置（DeepSeek 端点与 OpenAI 协议兼容）
client = OpenAI(
    api_key="sk-a5aaef985e1b4e2e9dac825af5ed7e32",
    base_url="https://api.deepseek.com",
)
MODEL = "deepseek-chat"

# ========== 2. Tools JSON Schema ==========
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间（通过系统命令）",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "计算某年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要判断的年份，如 2999"}
                },
                "required": ["year"],
                "additionalProperties": False,
            },
        },
    },
]

# ========== 3. 本地工具实现 ==========


def get_date() -> str:
    """调用 Windows 系统 cmd 获取日期和时间（绝不使用 datetime 模块）。"""
    # 先 chcp 65001 切 UTF-8 代码页，再用 utf-8 解码（GBK 会把中文星期解成乱码）
    def run(cmd: str) -> str:
        out = subprocess.run(
            ["cmd", "/c", f"chcp 65001 >nul & {cmd}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return out.stdout.strip()

    date_str = run("date /t")   # 如 "周一 2026/10/19"
    time_str = run("time /t")   # 如 "14:58"
    return f"{date_str} {time_str}"


def is_leap_year(year: int) -> str:
    """纯 Python 取模计算闰年，不调外部命令。"""
    # 闰年规则：能被4整除且不能被100整除，或能被400整除
    if year % 4 == 0 and year % 100 != 0 or year % 400 == 0:
        return f"{year} 年是闰年"
    return f"{year} 年不是闰年"


# 工具名 -> 可调用对象 的映射
TOOL_MAP = {
    "getDate": lambda _args: get_date(),
    "isLeapYear": lambda args: is_leap_year(args["year"]),
}

# ========== 4. 流式解析 tool_calls 辅助 ==========


def _init_tool_call(call_id, call_index, function_name=""):
    """初始化一个 tool_call 的缓冲区。"""
    return {
        "id": call_id,
        "index": call_index,
        "function": {"name": function_name, "arguments": ""},
    }


def parse_stream_chunk(chunk, tool_calls_accum: dict) -> str | None:
    """
    消费一个流式 chunk，返回文本内容（用于打字机显示），同时在 tool_calls_accum 中
    累积 tool_calls 的函数名和参数碎片。

    tool_calls_accum 结构：{ index: {id, index, function: {name, arguments}} }
    当某个 call 的 arguments 末尾以 '}' 结尾时，认为该 call 参数拼接完成。
    """
    content_text = None

    if not chunk.choices:
        return content_text

    delta = chunk.choices[0].delta

    # 处理普通文本回复
    if delta.content:
        content_text = delta.content

    # 处理 tool_calls 碎片
    if delta.tool_calls:
        for tc in delta.tool_calls:
            idx = tc.index
            # 首次出现：分配 id / name
            if idx not in tool_calls_accum:
                tool_calls_accum[idx] = _init_tool_call(
                    call_id=tc.id or f"call_{idx}",
                    call_index=idx,
                    function_name=tc.function.name or "",
                )
            else:
                # 后续碎片：补全 name（如果之前为空）或追加 arguments
                if tc.function.name and not tool_calls_accum[idx]["function"]["name"]:
                    tool_calls_accum[idx]["function"]["name"] = tc.function.name
                if tc.function.arguments:
                    tool_calls_accum[idx]["function"]["arguments"] += tc.function.arguments

    return content_text


def tool_calls_finished(tool_calls_accum: dict) -> list | None:
    """
    检查所有累积中的 tool_calls 是否都拼接完成（arguments 以 '}' 结尾 或 空参数）。
    完成则返回标准化列表，否则返回 None。
    """
    if not tool_calls_accum:
        return None
    for call in tool_calls_accum.values():
        args = call["function"]["arguments"].strip()
        # 有参数但没闭合 => 还没传完
        if args and not args.endswith("}"):
            return None
    # 全部完成，转为 JSON
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


# ========== 5. Agent 对话循环 ==========


def agent_chat(user_input: str, messages: list) -> None:
    """
    完整的 Agent Loop：
      用户输入 -> 流式调用模型 -> 若模型要调工具 -> 本地执行 -> tool 结果回传 -> 模型最终答复
    """
    messages.append({"role": "user", "content": user_input})

    while True:
        tool_calls_accum: dict = {}       # 本轮累积的 tool_calls 碎片
        assistant_content_buf: list = []   # 本轮文本回复缓冲
        assistant_tool_calls: list = []    # 本轮完整 tool_calls

        # --- 第 1 步：流式请求模型 ---
        stream = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            stream=True,
        )

        print("ai> ", end="", flush=True)

        for chunk in stream:
            # 解析 chunk，可能同时累积 tool_calls 和返回文本
            text = parse_stream_chunk(chunk, tool_calls_accum)
            if text:
                assistant_content_buf.append(text)
                print(text, end="", flush=True)

        # --- 第 2 步：检查是否需要调工具 ---
        finished_calls = tool_calls_finished(tool_calls_accum)

        # 构造 assistant 消息（必须带 tool_calls 字段才能让模型后续理解 tool 结果）
        assistant_msg = {
            "role": "assistant",
            "content": "".join(assistant_content_buf) or None,
        }
        if finished_calls:
            assistant_tool_calls = [
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
            assistant_msg["tool_calls"] = assistant_tool_calls
        messages.append(assistant_msg)

        # --- 第 3 步：如果有工具调用，执行并把结果喂回模型 ---
        if finished_calls:
            print()  # 换行准备输出工具执行日志
            for call in finished_calls:
                fname = call["function"]["name"]
                parsed_args = call["_parsed_args"]
                print(f"  [tool] {fname}({parsed_args}) => ", end="", flush=True)
                try:
                    result = TOOL_MAP[fname](parsed_args)
                except Exception as e:
                    result = f"工具执行出错: {e}"
                print(result)
                # 追加 tool 消息
                messages.append({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": str(result),
                })
            # 继续 while 循环，让模型基于 tool 结果生成最终答复
            continue

        # --- 第 4 步：没有工具调用 => 本轮结束 ---
        print()  # 最终答复后换行
        break


# ========== 6. 主入口 ==========

def main():
    messages: list = [
        {"role": "system", "content": "你是一个可以调用工具的智能助手。用户询问时间/日期时调用 getDate；询问闰年时调用 isLeapYear。工具结果出来后请直接给出自然语言总结。"}
    ]

    print("=== 流式 Agent（支持 Function Calling）===")
    print("输入 Ctrl+C 退出\n")

    # ---- 测试用例 1：获取当前时间 ----
    print("---- 测试用例 1：帮我看看现在几点了 ----")
    agent_chat("帮我看看现在几点了", messages)
    print()

    # ---- 测试用例 2：判断 2999 年是否闰年 ----
    print("---- 测试用例 2：2999 年是不是闰年？----")
    agent_chat("2999 年是不是闰年？", messages)
    print()

    # ---- 进入自由对话 ----
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
