"""
Skill 懒加载器 —— 扫描 .agents/skills/ 目录，仅加载元数据（name/description/path）。

设计原则：
  - 初始化阶段只读 SKILL.md 的 YAML Frontmatter（name + description）
  - 绝对不读取正文内容（正文按需加载，留给未来的 load_skill_detail 工具）
  - 目录不存在 / YAML 格式错误 / 缺少必需字段 → 静默跳过 + 警告，不崩溃
  - 以 os.getcwd() 作为项目根目录（规范要求）
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml


# ========== 数据结构 ==========

@dataclass(frozen=True)
class SkillMeta:
    """Skill 元数据（懒加载：只有这些，正文不在这儿）。"""
    name: str
    description: str
    path: str          # SKILL.md 的绝对路径（未来按需加载正文时用）
    version: str = ""

    def __repr__(self) -> str:
        return f"SkillMeta(name={self.name!r}, desc={self.description!r})"


# ========== Frontmatter 解析 ==========

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


def _parse_frontmatter(raw: str) -> Optional[dict]:
    """从 SKILL.md 原始文本中提取 YAML Frontmatter。

    返回解析后的 dict；没有 frontmatter 或 YAML 非法返回 None。
    """
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        return None
    try:
        data = yaml.safe_load(match.group(1))
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        return None
    return None


# ========== 扫描与加载 ==========

def _find_skills_dir(start: Path) -> Optional[Path]:
    """从 start 目录向上查找，直到找到包含 .agents/skills 的父目录。

    查找顺序：start → start.parent → ... → 根目录。
    找到就返回 Path；整条链都没找到返回 None。
    """
    cursor = start.resolve()
    for _ in range(20):  # 防无限循环，最多向上 20 层
        candidate = cursor / ".agents" / "skills"
        if candidate.is_dir():
            return candidate
        parent = cursor.parent
        if parent == cursor:  # 到根了
            break
        cursor = parent
    return None


def discover_skills(project_root: Optional[str] = None, verbose: bool = False) -> List[SkillMeta]:
    """扫描 .agents/skills/ 目录，返回所有 Skill 的元数据列表（懒加载）。

    查找策略：从 project_root（默认 os.getcwd()，打包模式下改用 exe 所在目录）
    开始向上查找 .agents/skills，找到第一个就用。

    Args:
        project_root: 起始查找目录；None 时：打包模式用 exe 所在目录，开发模式用 os.getcwd()
        verbose: True 时打印扫描过程（调试用）

    Returns:
        List[SkillMeta] — 成功解析的 skill 元数据；无 skill 时返回空列表
    """
    if project_root:
        start = Path(project_root)
    elif getattr(sys, "frozen", False):
        # 打包模式：从 exe 所在目录向上走，和用户"放 exe 在哪都行"的直觉一致
        start = Path(os.path.dirname(sys.executable))
    else:
        start = Path(os.getcwd())

    skills_dir = _find_skills_dir(start)

    if skills_dir is None:
        if verbose:
            print(f"[skill_loader] 未找到 .agents/skills 目录（从 {start} 向上查找）")
        return []

    if verbose:
        print(f"[skill_loader] 技能目录: {skills_dir}")

    skills: List[SkillMeta] = []
    for entry in sorted(skills_dir.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            if verbose:
                print(f"[skill_loader] 跳过 {entry.name}/ ：缺少 SKILL.md")
            continue

        try:
            raw = skill_md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            print(f"[skill_loader] [WARN]  无法读取 {skill_md}: {e}")
            continue

        fm = _parse_frontmatter(raw)
        if fm is None:
            print(f"[skill_loader] [WARN]  {skill_md} ：YAML Frontmatter 缺失或格式错误")
            continue

        name = str(fm.get("name", "")).strip()
        description = str(fm.get("description", "")).strip()

        if not name:
            print(f"[skill_loader] [WARN]  {skill_md} ：缺少必需字段 'name'，跳过")
            continue
        if not description:
            print(f"[skill_loader] [WARN]  {skill_md} ：缺少必需字段 'description'，跳过")
            continue

        skills.append(SkillMeta(
            name=name,
            description=description,
            path=str(skill_md.resolve()),
            version=str(fm.get("version", "")).strip(),
        ))
        if verbose:
            print(f"[skill_loader] [OK]    加载: {name} — {description}")

    return skills


# ========== 未来用：按需加载正文 ==========

def load_skill_body(skill: SkillMeta) -> str:
    """读取指定 Skill 的完整正文（包括 frontmatter）。

    仅在 Agent 判断需要某个 skill 时才调用，避免占用 System Prompt 空间。
    返回 SKILL.md 的完整内容；文件不存在返回空字符串。
    """
    try:
        return Path(skill.path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


# ========== 格式化器：注入到 System Prompt ==========

def format_skills_for_prompt(skills: List[SkillMeta]) -> str:
    """把 Skill 元数据列表格式化为 System Prompt 可直接插入的文本块。"""
    if not skills:
        return ""

    lines = ["", "You have access to the following skills:"]
    for s in skills:
        lines.append(f"- '{s.name}': {s.description}")

    lines.extend([
        "",
        "Use the 'loadSkill' tool to load the full instructions of a skill when needed. "
        "You can also load additional files referenced by a skill.",
    ])
    return "\n".join(lines)
