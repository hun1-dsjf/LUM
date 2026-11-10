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

from core.skill_loader import discover_skills, get_skills_dir, SkillMeta
from config.config_manager import AGENT_CONFIG


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

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _validate_skill_name(name: str) -> str | None:
    """校验 Skill 名称格式。

    规则：小写字母、数字、连字符组成，且以字母/数字开头，长度 >= 1。
    校验失败返回错误信息；通过返回 None。
    """
    name = name.strip()
    if not name:
        return "Skill 名称不能为空"
    if not _SKILL_NAME_RE.match(name):
        return (
            f"Skill 名称 '{name}' 格式不合法。"
            "名称只能由小写字母、数字和连字符(-)组成，"
            "且必须以字母或数字开头，例如 'code-review'、'html-report'。"
        )
    # 保留字（防止和工具名冲突）
    if name in {"loadskill", "createskill"}:
        return f"Skill 名称 '{name}' 是保留字，不能使用。"
    return None

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


def _truncate(text: str) -> tuple[str, bool]:
    """按 skill_max_chars 截断，返回 (内容, 是否截断)。"""
    limit = AGENT_CONFIG.skill_max_chars
    if limit > 0 and len(text) > limit:
        return (
            text[:limit]
            + f"\n\n...（内容超过 {limit} 字符，已截断，仅返回前 {limit} 字符）",
            True,
        )
    return text, False


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
    body, truncated = _truncate(body)
    return {
        "exit_code": 0,
        "skill_name": skill.name,
        "skill_dir": str(skill_dir),
        "file": "SKILL.md",
        "truncated": truncated,
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

    content, truncated = _truncate(content)
    return {
        "exit_code": 0,
        "skill_name": skill.name,
        "skill_dir": str(skill_dir),
        "file": str(resolved.relative_to(skill_dir)).replace("\\", "/"),
        "truncated": truncated,
        "content": content,
    }


# ========== 工具入口 ==========

def _reset_skill_cache() -> None:
    """强制刷新 Skill 元数据缓存（创建/删除 Skill 后调用）。"""
    global _cached_skills
    _cached_skills = None


def tool_create_skill(args: dict) -> str:
    """createSkill 工具入口：在 .agents/skills/<name>/ 下创建 SKILL.md。"""
    name = (args.get("name") or "").strip()
    skill_context = args.get("skillContext") or args.get("skill_context") or ""

    # 1. 参数校验
    err = _validate_skill_name(name)
    if err:
        return json.dumps({"exit_code": -1, "error": err}, ensure_ascii=False)

    if not skill_context.strip():
        return json.dumps({
            "exit_code": -1,
            "error": "参数 skillContext 不能为空——它是 SKILL.md 的完整内容（含 YAML Frontmatter）。",
        }, ensure_ascii=False)

    # 2. 查找（或创建）.agents/skills 目录
    skills_dir = get_skills_dir()
    if skills_dir is None:
        # 自动从当前工作目录向上探测，找到第一个存在的父目录来创建 .agents/skills
        start = Path(os.getcwd()).resolve()
        skills_dir = start / ".agents" / "skills"
        try:
            skills_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            return json.dumps({
                "exit_code": -1,
                "error": (
                    f"无法创建 .agents/skills/ 目录：{e}\n"
                    f"请检查权限或手动创建：{skills_dir}"
                ),
            }, ensure_ascii=False)

    # 3. 确定目标路径
    target_dir = (skills_dir / name).resolve()
    skill_md = target_dir / "SKILL.md"

    # 安全检查：目标不能逃逸到 skills_dir 之外
    try:
        target_dir.relative_to(skills_dir.resolve())
    except ValueError:
        return json.dumps({
            "exit_code": -1,
            "error": f"安全拦截：目标路径 {target_dir} 不在 skills 目录 {skills_dir} 内。",
        }, ensure_ascii=False)

    # 4. 冲突检测：目录已存在（不管是不是空目录）都拒绝覆盖
    if target_dir.exists():
        if skill_md.is_file():
            return json.dumps({
                "exit_code": -1,
                "error": (
                    f"Skill '{name}' 已存在：{skill_md}\n"
                    f"为避免意外覆盖，请先手动删除该 Skill 目录，"
                    f"或为新 Skill 使用其他名称。"
                ),
            }, ensure_ascii=False)
        # 目录存在但没有 SKILL.md——还是提示冲突，避免破坏可能存在的其他文件
        return json.dumps({
            "exit_code": -1,
            "error": (
                f"目录 '{target_dir}' 已存在但缺少 SKILL.md。\n"
                f"为避免覆盖目录内其他文件，请先手动清理后重试。"
            ),
        }, ensure_ascii=False)

    # 5. 创建目录并写入 SKILL.md
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
        skill_md.write_text(skill_context, encoding="utf-8")
    except (OSError, PermissionError) as e:
        # 清理半创建的空目录
        if target_dir.is_dir() and not any(target_dir.iterdir()):
            try:
                target_dir.rmdir()
            except OSError:
                pass
        return json.dumps({
            "exit_code": -1,
            "error": f"创建 Skill 失败：{e}",
        }, ensure_ascii=False)

    # 6. 刷新 Skill 缓存，让新 Skill 立即可用
    _reset_skill_cache()

    print(f"[系统] 创建 Skill 成功：{name}  ->  {skill_md}", file=sys.stderr, flush=True)

    return json.dumps({
        "exit_code": 0,
        "skill_name": name,
        "skill_dir": str(target_dir),
        "file": str(skill_md),
        "message": (
            f"Skill '{name}' 创建成功。\n"
            f"- SKILL.md 路径：{skill_md}\n"
            f"- 如需添加 references/、scripts/ 等子目录或其他辅助文件，"
            f"请继续使用 fileOps 工具完成。"
        ),
    }, ensure_ascii=False)


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
    },
    {
        "type": "function",
        "function": {
            "name": "createSkill",
            "description": (
                "根据用户的自然语言要求创建一个新的 Skill。\n"
                "该工具会在项目的 .agents/skills/<name>/ 目录下生成 SKILL.md 文件。\n"
                "如果需要添加 references/、scripts/ 等子目录或其他辅助文件，"
                "请在 createSkill 成功后继续使用 fileOps 工具完成。\n\n"
                "Skill 名称规范：只能包含小写字母、数字和连字符(-)，"
                "如 'code-review'、'html-report'、'api-test'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": (
                            "Skill 名称。只能由小写字母、数字和连字符(-)组成，"
                            "必须以字母或数字开头。例如 'code-review'、'html-report'。"
                        ),
                    },
                    "skillContext": {
                        "type": "string",
                        "description": (
                            "要写入 SKILL.md 的完整内容，必须包含正确的 YAML Frontmatter，"
                            "格式：\n"
                            "---\n"
                            "name: <skill-name>\n"
                            "description: <一句话描述>\n"
                            "version: \"1.0.0\"\n"
                            "---\n\n"
                            "<正文内容：具体的技能指令、使用规则、步骤等>"
                        ),
                    },
                },
                "required": ["name", "skillContext"],
                "additionalProperties": False,
            },
        },
    },
]

SKILL_TOOL_MAP = {
    "loadSkill": tool_load_skill,
    "createSkill": tool_create_skill,
}
