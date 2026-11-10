"""
XAgent 核心引擎 —— Core 与 UI 彻底分离。

设计原则：
  - 零 print、零 UI 库依赖（Core 层绝对纯逻辑）
  - AsyncOpenAI 异步流式调用，避免阻塞 UI 事件循环
  - EventCallback 协议：UI 层传入自己的实现，Core 只负责回调事件
  - 未来接 FastAPI / PyQt / Web 只需写新的 Callback 实现
  - 上下文管理：stream_options 开启 include_usage，保留 token 用量；
    暴露 trigger_compaction() 异步方法供 TUI 调用 /compact
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from openai import AsyncOpenAI

from config.config_manager import AGENT_CONFIG, SANDBOX_ROOT
from core.skill_loader import discover_skills, format_skills_for_prompt
from core.trace import trace


# ========== 事件回调协议（Core → UI）==========

class EventCallback(Protocol):
    """UI 层实现此协议，接收 Core 层推送的事件。"""

    def on_text_delta(self, delta: str) -> None: ...
    def on_tool_start(self, name: str, args: dict) -> None: ...
    def on_tool_result(self, name: str, args: dict, result: str) -> None: ...
    def on_ai_done(self, full_text: str) -> None: ...

    # —— 上下文压缩相关（可选实现）——
    def on_context_usage(self, current: int, window: int, percent: float) -> None: ...
    def on_context_warning(self, percent: float) -> None: ...
    def on_compaction_start(self) -> None: ...
    def on_compaction_done(self, archive_id: str) -> None: ...
    def on_compaction_failed(self, error: str) -> None: ...


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

_BASE_SYSTEM_PROMPT = (
    "你是一个智能助手，可以调用以下工具："
    "1) 本地文件操作工具（查看/编辑/创建/删除文件和目录，操作范围严格限制在 XAgent 目录内）；"
    "2) 时间工具 getCurrentTime / isLeapYear（涉及今天、现在、闰年时必须先调用，禁止凭记忆回答）；"
    "3) searchWeb 联网搜索工具（获取实时信息、最新资讯、你不知道的外部知识，返回标题+摘要+URL）；"
    "4) fetchWeb 网页抓取工具（对 searchWeb 返回的某个 URL 深入抓取正文，转为 Markdown）；"
    "5) runCli 本地命令行执行工具（运行已安装的 CLI 程序，如 python/git/ipconfig/ver 等）；"
    "6) createSkill / loadSkill 技能工具（把可复用流程沉淀为技能，或按需加载技能说明）；"
    "7) recallContext 历史归档检索工具（当你被 compact 替换了上下文时，用它查过去聊过什么）。"
    "使用策略：先用 searchWeb 找到相关来源，如需详细阅读某条结果再用 fetchWeb；"
    "直接给你一个 URL 时可以直接 fetchWeb；需要系统信息或运行开发工具时用 runCli；"
    "当需要回忆之前对话（用户提过的需求、做过的工作、关键决策）时用 recallContext。"
    "工具结果出来后请直接给出自然语言总结，不要输出 JSON 或工具名。"
    f"所有文件操作被限制在以下目录内，不能访问该目录之外的路径：{SANDBOX_ROOT}"
)


@dataclass
class Agent:
    """Agent 核心引擎（可复用实例，多轮对话共享 messages）。"""
    config: LLMConfig
    callback: EventCallback | None = None
    skills: list = field(default_factory=lambda: discover_skills(verbose=True))
    tools_schema: list[dict] = field(default_factory=list)
    tool_map: dict[str, Callable[[dict], str]] = field(default_factory=dict)

    # —— 上下文管理 ——
    window_size: int = field(default_factory=lambda: AGENT_CONFIG.window_size)
    max_steps: int = field(default_factory=lambda: AGENT_CONFIG.max_steps)
    turn_timeout: int = field(default_factory=lambda: AGENT_CONFIG.turn_timeout)
    last_usage: dict = field(default_factory=dict)   # 最近一次 LLM 返回的 usage 字段
    _compacting: bool = False                          # 防止并发 compaction

    def __post_init__(self) -> None:
        if not self.tools_schema or not self.tool_map:
            from tools import TOOLS_SCHEMA, TOOL_MAP
            if not self.tools_schema:
                self.tools_schema = TOOLS_SCHEMA
            if not self.tool_map:
                self.tool_map = TOOL_MAP

        skills_block = format_skills_for_prompt(self.skills)
        full_prompt = _BASE_SYSTEM_PROMPT + skills_block
        self.messages = [{"role": "system", "content": full_prompt}]

    # ---------- 上下文状态 ----------

    def context_status(self) -> dict:
        """返回当前上下文用量信息（供 UI 状态栏和阈值判断使用）。"""
        from core.context_manager import estimate_messages_tokens
        current = estimate_messages_tokens(self.messages)
        pct = current / self.window_size * 100
        return {
            "current": current,
            "window": self.window_size,
            "percent": round(pct, 1),
            "messages_count": len(self.messages),
            "compacting": self._compacting,
        }

    # ---------- LLM 客户端 ----------

    def _build_client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
        )

    # ---------- Chat 主循环 ----------

    async def chat(self, user_input: str) -> None:
        """完整 Agent Loop。"""
        if self._compacting:
            if self.callback:
                try:
                    self.callback.on_context_warning(0.0)  # 特殊值：正在压缩
                except Exception:
                    pass
            raise RuntimeError("上下文压缩进行中，请稍候再试")

        self.messages.append({"role": "user", "content": user_input})
        client = self._build_client()
        trace("user_message", content=user_input[:500])

        turn_start = time.monotonic()
        steps = 0
        while True:
            steps += 1
            if steps > self.max_steps:
                notice = f"已达到最大工具调用步数（{self.max_steps}），本轮已停止。"
                self._finish_with_notice(notice)
                trace("max_steps", steps=steps - 1)
                return
            elapsed = time.monotonic() - turn_start
            if elapsed > self.turn_timeout:
                notice = f"本轮对话超过 {self.turn_timeout}s 超时保护，已停止。"
                self._finish_with_notice(notice)
                trace("turn_timeout", elapsed_ms=int(elapsed * 1000))
                return

            tool_calls_accum: dict = {}
            assistant_content_buf: list[str] = []
            last_chunk = None  # 最后一个 chunk 里有 usage

            stream = await client.chat.completions.create(
                model=self.config.model,
                messages=self.messages,
                tools=self.tools_schema,
                stream=True,
                stream_options={"include_usage": True},
            )

            async for chunk in stream:
                last_chunk = chunk
                text = _parse_stream_chunk(chunk, tool_calls_accum)
                if text:
                    assistant_content_buf.append(text)
                    if self.callback:
                        try:
                            self.callback.on_text_delta(text)
                        except Exception:
                            pass

            # —— 上下文用量 ——
            usage = getattr(last_chunk, "usage", None)
            current_prompt = 0
            if usage:
                self.last_usage = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(usage, "completion_tokens", 0),
                    "total_tokens": getattr(usage, "total_tokens", 0),
                }
                current_prompt = self.last_usage["prompt_tokens"]
            else:
                from core.context_manager import estimate_messages_tokens
                current_prompt = estimate_messages_tokens(self.messages)

            if self.callback:
                try:
                    self.callback.on_context_usage(
                        current=current_prompt,
                        window=self.window_size,
                        percent=round(current_prompt / self.window_size * 100, 1),
                    )
                except Exception:
                    pass

            # 阈值警告
            pct = current_prompt / self.window_size * 100
            if pct >= 90:
                if self.callback:
                    try:
                        self.callback.on_context_warning(pct)
                    except Exception:
                        pass
            elif pct >= 80:
                if self.callback:
                    try:
                        self.callback.on_context_warning(pct)
                    except Exception:
                        pass

            finished_calls = _tool_calls_finished(tool_calls_accum)

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

            if finished_calls:
                for call in finished_calls:
                    fname = call["function"]["name"]
                    parsed_args = call["_parsed_args"]
                    if self.callback:
                        try:
                            self.callback.on_tool_start(fname, parsed_args)
                        except Exception:
                            pass
                    tool_started = time.monotonic()
                    status = "ok"
                    trace("tool_call", tool=fname, args=parsed_args)
                    try:
                        result = self.tool_map[fname](parsed_args)
                    except KeyError:
                        status = "not_found"
                        result = f"错误: 未注册的工具 '{fname}'"
                    except Exception as e:
                        status = "error"
                        result = f"工具执行出错: {e}"
                    trace(
                        "tool_result",
                        tool=fname,
                        status=status,
                        duration_ms=int((time.monotonic() - tool_started) * 1000),
                        result_preview=str(result)[:300],
                    )
                    if self.callback:
                        try:
                            self.callback.on_tool_result(fname, parsed_args, result)
                        except Exception:
                            pass
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": str(result),
                    })
                continue

            trace("turn_done", steps=steps, usage=self.last_usage)
            if self.callback:
                try:
                    self.callback.on_ai_done("".join(assistant_content_buf))
                except Exception:
                    pass
            break

    def _finish_with_notice(self, notice: str) -> None:
        """以一条可见提示结束本轮（步数/超时保护触发时使用）。"""
        self.messages.append({"role": "assistant", "content": notice})
        if self.callback:
            try:
                self.callback.on_text_delta(notice)
                self.callback.on_ai_done(notice)
            except Exception:
                pass

    # ---------- 上下文压缩（TUI 通过 /compact 触发）----------

    async def trigger_compaction(self) -> str:
        """
        手动触发上下文压缩。返回 archive_id。

        流程：归档 → LLM 生成摘要 → 替换 messages（只保留 system + 摘要 user）。
        失败时保留原 messages 不动，抛异常让上层处理。
        """
        if self._compacting:
            raise RuntimeError("压缩已在进行中")
        self._compacting = True

        if self.callback:
            try:
                self.callback.on_compaction_start()
            except Exception:
                pass

        try:
            from core.context_manager import perform_compaction

            client = self._build_client()
            new_messages, archive_id = await perform_compaction(
                client=client,
                model=self.config.model,
                messages=self.messages,
                window_size=self.window_size,
            )
            self.messages = new_messages

            if self.callback:
                try:
                    self.callback.on_compaction_done(archive_id)
                except Exception:
                    pass
            return archive_id

        except Exception as e:
            import traceback
            traceback.print_exc()
            if self.callback:
                try:
                    self.callback.on_compaction_failed(str(e))
                except Exception:
                    pass
            raise
        finally:
            self._compacting = False
