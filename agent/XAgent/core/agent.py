"""
XAgent 核心引擎 —— Core 与 UI 彻底分离。

设计原则：
  - 零 print、零 UI 库依赖（Core 层绝对纯逻辑）
  - AsyncOpenAI 异步流式调用，避免阻塞 UI 事件循环
  - EventCallback 协议：UI 层传入自己的实现，Core 只负责回调事件
  - 未来接 FastAPI / PyQt / Web 只需写新的 Callback 实现
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Protocol

from openai import AsyncOpenAI

from config.settings import LLMConfig, SANDBOX_ROOT
from tools import TOOL_MAP, TOOLS_SCHEMA


# ========== 事件回调协议（Core → UI）==========

class EventCallback(Protocol):
    """UI 层实现此协议，接收 Core 层推送的事件。"""

    def on_text_delta(self, delta: str) -> None:
        """流式文本增量输出（打字机）。"""
        ...

    def on_tool_start(self, name: str, args: dict) -> None:
        """工具开始执行。"""
        ...

    def on_tool_result(self, name: str, args: dict, result: str) -> None:
        """工具执行完毕。"""
        ...

    def on_ai_done(self, full_text: str) -> None:
        """AI 本轮回复结束（可空）。"""
        ...


# ========== 流式 tool_calls 解析辅助 ==========

def _init_tool_call(call_id: str, call_index: int, function_name: str = "") -> dict:
    return {
        "id": call_id,
        "index": call_index,
        "function": {"name": function_name, "arguments": ""},
    }


def _parse_stream_chunk(chunk, tool_calls_accum: dict) -> str | None:
    """消费流式 chunk，返回文本增量，同时累积 tool_calls 碎片。"""
    if not chunk.choices:
        return None
    delta = chunk.choices[0].delta
    content_text = delta.content if delta.content else None

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


def _tool_calls_finished(tool_calls_accum: dict) -> list | None:
    """判断所有累积 call 的 arguments 是否已闭合。"""
    if not tool_calls_accum:
        return None
    for call in tool_calls_accum.values():
        args = call["function"]["arguments"].strip()
        if args and not args.endswith("}"):
            return None
    result = []
    for call in tool_calls_accum.values():
        args_str = call["function"]["arguments"].strip() or "{}"
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


# ========== Agent 引擎 ==========

SYSTEM_PROMPT = (
    "你是一个智能助手，可以调用四类工具："
    "1) 本地文件操作工具（查看/编辑/创建/删除文件和目录，操作范围严格限制在 XAgent 目录内）；"
    "2) searchWeb 联网搜索工具（获取实时信息、最新资讯、你不知道的外部知识，返回标题+摘要+URL）；"
    "3) fetchWeb 网页抓取工具（对 searchWeb 返回的某个 URL 深入抓取正文，转为 Markdown）；"
    "4) runCli 本地命令行执行工具（运行已安装的 CLI 程序，如 python/git/ipconfig/ver 等）。"
    "使用策略：先用 searchWeb 找到相关来源，如需详细阅读某条结果再用 fetchWeb；"
    "直接给你一个 URL 时可以直接 fetchWeb；需要系统信息或运行开发工具时用 runCli。"
    "工具结果出来后请直接给出自然语言总结，不要输出 JSON 或工具名。"
    f"所有文件操作被限制在以下目录内，不能访问该目录之外的路径：{SANDBOX_ROOT}"
)


@dataclass
class Agent:
    """Agent 核心引擎（可复用实例，多轮对话共享 messages）。"""
    config: LLMConfig
    callback: EventCallback
    messages: list = field(default_factory=lambda: [
        {"role": "system", "content": SYSTEM_PROMPT}
    ])

    def _build_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    async def chat(self, user_input: str) -> None:
        """完整 Agent Loop：用户输入 → 流式请求 → 工具调用 → 结果回灌 → 最终回复。"""
        self.messages.append({"role": "user", "content": user_input})
        client = self._build_client()

        while True:
            tool_calls_accum: dict = {}
            assistant_content_buf: list[str] = []

            stream = await client.chat.completions.create(
                model=self.config.model,
                messages=self.messages,
                tools=TOOLS_SCHEMA,
                stream=True,
            )

            async for chunk in stream:
                text = _parse_stream_chunk(chunk, tool_calls_accum)
                if text:
                    assistant_content_buf.append(text)
                    self.callback.on_text_delta(text)

            finished_calls = _tool_calls_finished(tool_calls_accum)

            # 构造 assistant 消息（必须带 tool_calls 才能让模型关联后续 tool 消息）
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
            self.messages.append(assistant_msg)

            # 执行工具 → 结果回灌 → 继续循环
            if finished_calls:
                for call in finished_calls:
                    fname = call["function"]["name"]
                    parsed_args = call["_parsed_args"]
                    self.callback.on_tool_start(fname, parsed_args)
                    try:
                        result = TOOL_MAP[fname](parsed_args)
                    except KeyError:
                        result = f"错误: 未注册的工具 '{fname}'"
                    except Exception as e:
                        result = f"工具执行出错: {e}"
                    self.callback.on_tool_result(fname, parsed_args, result)
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": str(result),
                    })
                continue

            # 无工具调用 → 本轮结束
            self.callback.on_ai_done("".join(assistant_content_buf))
            break
