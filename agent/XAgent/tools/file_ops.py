"""
本地文件操作工具（10 个），带沙箱路径安全校验。

所有文件操作被限制在 SANDBOX_ROOT 目录内，拒绝空路径/根目录/父目录穿越。
"""
from __future__ import annotations

import os
import shutil

from config.settings import SANDBOX_ROOT


# ========== 路径安全校验 ==========

def _validate_path(raw_path: str, must_exist: bool = False,
                   must_be_file: bool = False, must_be_dir: bool = False) -> str:
    """统一路径校验：解析绝对路径、拒绝危险路径、限制在沙箱内。"""
    if not raw_path or not raw_path.strip():
        raise ValueError("路径不能为空")

    abs_path = os.path.abspath(os.path.join(SANDBOX_ROOT, raw_path)) \
        if not os.path.isabs(raw_path) else os.path.abspath(raw_path)

    # 拒绝盘根目录
    if abs_path in (os.path.abspath("/"), os.path.abspath("\\"),
                    os.path.abspath("C:\\"), os.path.abspath("D:\\")):
        raise ValueError(f"禁止操作根目录: {abs_path}")

    # 拒绝父目录穿越
    if not (abs_path == SANDBOX_ROOT or abs_path.startswith(SANDBOX_ROOT + os.sep)):
        raise ValueError(f"路径超出沙箱范围: {raw_path} -> {abs_path}")

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
    """检测前 8192 字节是否含 \\x00 判断文本/二进制。"""
    try:
        with open(file_path, "rb") as f:
            return b"\x00" not in f.read(8192)
    except OSError:
        return False


# ========== 工具实现 ==========

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
            entries.append(f"[FILE] {name} ({os.path.getsize(full)} bytes)")
    header = f"目录 {path} 下共 {len(entries)} 项:"
    return header + "\n" + "\n".join(entries) if entries else header + "\n(空)"


def tool_get_file_type(args: dict) -> str:
    path = _validate_path(args.get("path", "."), must_exist=True)
    if os.path.isdir(path):
        return f"{path} 是目录"
    ext = os.path.splitext(path)[1].lower() or "(无扩展名)"
    return (f"{path}\n  扩展名: {ext}\n"
            f"  类型: {'纯文本' if _is_text_file(path) else '二进制'}\n"
            f"  大小: {os.path.getsize(path)} bytes")


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
    if os.sep in filename or "/" in filename or "\\" in filename:
        return f"错误: filename 不能含路径分隔符: {filename}"
    content = args.get("content", "") or ""
    full_path = os.path.join(dir_path, filename)
    if os.path.exists(full_path):
        return f"错误: 文件已存在 {full_path}"
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
        else:
            old = args.get("old", "") or ""
            new = args.get("new", "") or ""
            if old not in original:
                return "错误: 原文本在文件中未找到，无法替换"
            new_content = original.replace(old, new)
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except OSError as e:
        return f"编辑失败: {e}"
    return f"已编辑 {path}（mode={mode}），新大小 {len(new_content.encode('utf-8'))} bytes"


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
    new_path = _validate_path(new_path_raw)
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


# ========== 工具注册表 ==========

# JSON Schema 声明（发给模型）
TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "get_cwd", "description": "获取当前工作目录（沙箱根目录的绝对路径）",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "list_dir", "description": "列出指定目录下的所有文件和子目录（仅允许沙箱范围内）",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "目录路径（可传相对/绝对）"}},
                    "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "get_file_type", "description": "获取指定文件的文件类型（扩展名/目录/大小/文本或二进制）",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文件路径"}},
                    "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "read_file", "description": "读取指定纯文本文件的完整内容（二进制文件会返回错误）",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "文本文件路径"}},
                    "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_file", "description": "在指定目录下创建一个新的纯文本文件",
     "parameters": {"type": "object", "properties": {
         "dir": {"type": "string", "description": "目标目录路径"},
         "filename": {"type": "string", "description": "新文件名"},
         "content": {"type": "string", "description": "文件初始内容"}
     }, "required": ["dir", "filename", "content"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "edit_file", "description": "编辑指定纯文本文件内容。mode=overwrite/append/replace",
     "parameters": {"type": "object", "properties": {
         "path": {"type": "string", "description": "要编辑的文件路径"},
         "mode": {"type": "string", "enum": ["overwrite", "append", "replace"], "description": "编辑模式"},
         "content": {"type": "string", "description": "overwrite/append 时的内容"},
         "old": {"type": "string", "description": "replace 时要被替换的原文本"},
         "new": {"type": "string", "description": "replace 时替换成的新文本"}
     }, "required": ["path", "mode"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "create_dir", "description": "创建新目录（支持递归创建）",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "新目录路径"}},
                    "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "delete_dir", "description": "删除目录（支持非空递归删除，危险操作）",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "要删除的目录路径"}},
                    "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "delete_file", "description": "删除指定文件（危险操作）",
     "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "要删除的文件路径"}},
                    "required": ["path"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "rename_path", "description": "重命名文件或目录（仅支持同目录改名）",
     "parameters": {"type": "object", "properties": {
         "old_path": {"type": "string", "description": "原路径"},
         "new_path": {"type": "string", "description": "新路径（必须同目录）"}
     }, "required": ["old_path", "new_path"], "additionalProperties": False}}},
]

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
