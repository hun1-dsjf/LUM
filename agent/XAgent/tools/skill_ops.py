"""
Skill 操作工具 —— loadSkill。

按需加载某个 Skill 的完整 SKILL.md 正文，或其目录下的附加文件。

安全设计：
  - 所有文件路径先 os.path.abspath → 校验前缀在 Skill 目录内
  - 禁止 .. / 绝对路径穿越到 Skill 目录外
  - 递归搜索只在 Skill 目录内进行
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List

from core.skill_loader import discover_skills, SkillMeta


# ========== 缓存与查找 ==========

_cached_skills: List[SkillMeta] | None = None


def _get_skills() -> List[SkillMeta]:
    global _cached_skills
    if _cached_skills is None:
        _cached_skills = discover_skills(verbose=False)
    return _cached_skills


def _find_skill(skill_name: str) -> SkillMeta | None:
    """按 name 查找 skill（精确匹配）。"""
    for s in _get_skills():
        if s.name == skill_name:
            return s
    return None


# ========== 路径安全工具 ==========

def _skill_dir(skill: SkillMeta) -> Path:
    """Skill 的绝对目录（SKILL.md 的父目录）。"""
    return Path(skill.path).parent.resolve()


def _safe_resolve(skill_dir: Path, target: str) -> Path | None:
    """解析目标路径，校验不越界。返回绝对路径；越界返回 None。"""
    # 绝对路径 → 直接用（但必须在 skill_dir 内）
    if os.path.isabs(target):
        resolved = Path(target).resolve()
    else:
        resolved = (skill_dir / target).resolve()

    # 安全检查：必须以 skill_dir 开头
    try:
        resolved.relative_to(skill_dir)
    except ValueError:
        return None
    return resolved


_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)


def _strip_frontmatter(raw: str) -> str:
    """去掉 YAML Frontmatter 头部，只返回 Markdown 正文。"""
    return _FRONTMATTER_RE.sub("", raw, count=1).strip()


def _read_safe(path: Path) -> str:
    """安全读取文件，捕获所有异常。"""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk", errors="replace")
    except (OSError, PermissionError) as e:
        return f"[读取失败: {e}]"


# ========== 核心执行逻辑 ==========

def _load_skill_md(skill: SkillMeta) -> dict:
    """读取 SKILL.md 正文（去除 YAML Frontmatter）。"""
    skill_dir = _skill_dir(skill)
    skill_md = skill_dir / "SKILL.md"

    if not skill_md.is_file():
        return {
            "exit_code": -1,
            "error": f"SKILL.md 不存在: {skill_md}",
        }

    raw = _read_safe(skill_md)
    if raw.startswith("[读取失败"):
        return {"exit_code": -1, "error": raw}

    body = _strip_frontmatter(raw)
    return {
        "exit_code": 0,
        "skill_name": skill.name,
        "skill_dir": str(skill_dir),
        "file": "SKILL.md",
        "content": body or "(文件无正文内容)",
    }


def _load_skill_file(skill: SkillMeta, filename: str) -> dict:
    """读取 Skill 目录下的附加文件。

    路径优先级：
      1. 绝对路径 → 必须在 skill_dir 内
      2. 相对路径 → 拼到 skill_dir 后解析
      3. 纯文件名 → rglob 递归搜索，唯一匹配才返回
    """
    skill_dir = _skill_dir(skill)

    # 1 & 2：尝试路径解析
    # 绝对路径且已在 skill_dir 内 → 直接读
    if os.path.isabs(filename):
        resolved = Path(filename).resolve()
    # 含路径分隔符 → 相对 skill_dir
    elif os.sep in filename or "/" in filename or "\\" in filename:
        resolved = (skill_dir / filename).resolve()
    # 3：纯文件名 → 递归搜索
    else:
        matches = list(skill_dir.rglob(filename))
        if not matches:
            return {
                "exit_code": -1,
                "error": f"在 Skill '{skill.name}' 目录内未找到文件 '{filename}'",
            }
        if len(matches) > 1:
            candidates = [str(p.relative_to(skill_dir)).replace("\\", "/") for p in matches]
            cand_list = "\n".join(f"  - {c}" for c in sorted(candidates))
            return {
                "exit_code": -1,
                "error": (
                    f"文件 '{filename}' 找到多个同名副本，请指定更精确的路径：\n"
                    f"{cand_list}"
                ),
            }
        # 唯一匹配，继续校验
        resolved = matches[0].resolve()

    # 安全校验：解析后的绝对路径必须在 skill_dir 内
    try:
        resolved.relative_to(skill_dir)
    except ValueError:
        return {
            "exit_code": -1,
            "error": "安全拦截：禁止读取 Skill 目录之外的文件。",
        }

    if not resolved.is_file():
        return {
            "exit_code": -1,
            "error": f"文件不存在: {filename}",
        }

    content = _read_safe(resolved)
    if content.startswith("[读取失败"):
        return {"exit_code": -1, "error": content}

    return {
        "exit_code": 0,
        "skill_name": skill.name,
        "skill_dir": str(skill_dir),
        "file": str(resolved.relative_to(skill_dir)).replace("\\", "/"),
        "content": content,
    }


# ========== 工具入口 ==========

def tool_load_skill(args: dict) -> str:
    """loadSkill 工具入口。"""
    name = (args.get("name") or args.get("skill_name") or "").strip()
    filename = (args.get("filename") or "").strip()

    if not name:
        return json.dumps({"exit_code": -1, "error": "参数 name 不能为空"}, ensure_ascii=False)

    skill = _find_skill(name)
    if skill is None:
        available = ", ".join(f"'{s.name}'" for s in _get_skills()) or "(无)"
        return json.dumps({
            "exit_code": -1,
            "error": f"未找到技能 '{name}'。当前可用技能: {available}",
        }, ensure_ascii=False)

    print(f"[系统] 准备加载技能：{name}  (dir={_skill_dir(skill)})", file=sys.stderr, flush=True)

    if filename:
        result = _load_skill_file(skill, filename)
    else:
        result = _load_skill_md(skill)

    return json.dumps(result, ensure_ascii=False)


# ========== 工具注册 ==========

SKILL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "loadSkill",
            "description": (
                "按需加载某个技能的完整指令内容或附加文件。\n"
                "- 只传 name：返回 SKILL.md 的 Markdown 正文（YAML 头部自动剥离）\n"
                "- 同时传 filename：读取该 Skill 目录下的附加文件（支持相对路径、绝对路径、纯文件名三种形式）\n"
                "安全限制：所有路径必须在 Skill 自身目录内，禁止读取目录外的文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要加载的技能名称（与 System Prompt 中列出的名称精确匹配）",
                    },
                    "filename": {
                        "type": "string",
                        "description": (
                            "可选。读取 Skill 目录下的指定文件："
                            "1) 相对路径：拼到 Skill 目录后读取；"
                            "2) 纯文件名：递归搜索 Skill 目录，唯一匹配才返回；"
                            "3) 绝对路径：必须在 Skill 目录内。"
                        ),
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    }
]

SKILL_TOOL_MAP = {
    "loadSkill": tool_load_skill,
}
