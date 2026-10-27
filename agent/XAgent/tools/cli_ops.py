"""
CLI 命令执行工具 —— RunCli。

通过 subprocess.run() 以列表方式执行命令行程序（shell=False），
捕获 stdout/stderr/exit_code，输出截断保护 + 完整异常处理。

编码策略：Windows 命令行默认输出 GBK/cp936，直接指定 encoding="utf-8" 会乱码。
解决方案：先 capture raw bytes，再按优先级尝试解码：
  1. locale.getpreferredencoding()（Windows 中文系统 = cp936/GBK）
  2. UTF-8（Python/git 等现代工具常用）
  3. GBK 兜底（Windows 内置命令如 dir/tasklist）

安全要点：
  - command + args 拼成列表传参，绝对不拼接字符串（防命令注入）
  - Windows 下某些内置命令（dir/echo/cd）不是 .exe，需要走 cmd.exe
"""
from __future__ import annotations

import json
import locale
import subprocess
import sys


# ========== 常量 ==========

_TIMEOUT = 15            # 秒
_MAX_OUTPUT = 2000       # stdout/stderr 单条最大字符数

# Windows 内置命令映射：这些没有 .exe，必须走 cmd.exe /c
_WIN_BUILTINS = {
    "dir", "echo", "cd", "cls", "copy", "del", "md", "mkdir",
    "rd", "rmdir", "ren", "type", "set", "where", "whoami",
    "ver", "vol", "label", "attrib", "fc", "find", "sort",
    "tree", "more", "pause", "title", "prompt", "path",
}


def _decode_output(raw: bytes) -> str:
    """Windows 命令行输出智能解码：先试系统编码，再 UTF-8，最后 GBK。"""
    if not raw:
        return ""
    # 优先级 1：系统首选编码（中文 Windows = cp936/GBK）
    sys_enc = locale.getpreferredencoding(False)
    for enc in (sys_enc, "utf-8", "gbk", "cp936", "replace"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # 兜底：完全替换无法解码的字节
    return raw.decode("utf-8", errors="replace")


def _truncate(text: str, max_len: int = _MAX_OUTPUT) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n...[输出过长，已截断]"


def _normalize_args(args) -> list[str]:
    """确保 args 是字符串列表，处理 None / 字符串 / 列表三种输入。"""
    if args is None:
        return []
    if isinstance(args, str):
        # 单个字符串参数（如 "--help"）
        return [args]
    if isinstance(args, (list, tuple)):
        return [str(a) for a in args]
    return [str(args)]


def tool_run_cli(args: dict) -> str:
    """RunCli 工具入口：执行本地命令行程序。"""
    command = (args.get("command") or "").strip()
    cli_args = _normalize_args(args.get("args"))
    timeout = int(args.get("timeout", _TIMEOUT))

    if not command:
        return json.dumps({"exit_code": -1, "stdout": "", "stderr": "错误: command 不能为空"},
                          ensure_ascii=False)

    # 拼装命令列表：Windows 内置命令走 cmd.exe /c
    cmd_list: list[str]
    if command.lower() in _WIN_BUILTINS:
        # 走 cmd.exe /c，把 command + args 拼成一串作为 /c 的参数
        cmd_list = ["cmd.exe", "/c", command] + cli_args
    else:
        cmd_list = [command] + cli_args

    try:
        # capture_output=True 拿 bytes，由我们自己决定解码方式
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            timeout=timeout,
            shell=False,   # 关键！防命令注入
        )
    except FileNotFoundError:
        return json.dumps({
            "exit_code": -1,
            "stdout": "",
            "stderr": f"程序未找到: {command!r}（请确认已安装或在 PATH 中）",
        }, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({
            "exit_code": -1,
            "stdout": "",
            "stderr": f"执行超时（超过 {timeout} 秒）",
        }, ensure_ascii=False)
    except OSError as e:
        return json.dumps({
            "exit_code": -1,
            "stdout": "",
            "stderr": f"启动失败: {e}",
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({
            "exit_code": -1,
            "stdout": "",
            "stderr": f"未知错误: {e}",
        }, ensure_ascii=False)

    stdout = _decode_output(result.stdout)
    stderr = _decode_output(result.stderr)

    return json.dumps({
        "exit_code": result.returncode,
        "stdout": _truncate(stdout),
        "stderr": _truncate(stderr),
    }, ensure_ascii=False)


# ========== 工具注册 ==========

CLI_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "runCli",
            "description": (
                "在本地执行命令行程序。"
                "当用户需要查看系统信息（ipconfig/ver）、运行开发工具（python/git/node）、"
                "或执行任何已安装的 CLI 程序时调用。"
                "注意：工具只返回原始输出，你需要解读 exit_code（0=成功，非 0=失败）和内容。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要执行的程序名（如 python、git、ipconfig、dir）",
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "传递给程序的参数列表，如 ['--version'] 或 ['-l', '-a']",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时秒数，默认 15，最大 60",
                        "default": 15,
                    },
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }
]

CLI_TOOL_MAP = {
    "runCli": tool_run_cli,
}
