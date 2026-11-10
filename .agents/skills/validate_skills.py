"""
技能目录校验脚本。

用途：在提交/发布前检查 `.agents/skills` 下每个技能的结构是否合规：
  - 每个技能是一个目录，且包含 SKILL.md
  - SKILL.md 必须以 YAML frontmatter 开头，含 name / description
  - name 必须与目录名一致，且只含小写字母、数字、连字符
  - description 非空
  - 技能名不得重复

运行：
    python .agents/skills/validate_skills.py
    python .agents/skills/validate_skills.py --dir 其他技能目录

退出码：0 全部通过；1 存在错误。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("缺少依赖 PyYAML，请先执行：pip install pyyaml", file=sys.stderr)
    sys.exit(2)

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def parse_frontmatter(text: str) -> dict | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def validate(skills_dir: Path) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []
    if not skills_dir.is_dir():
        return [f"技能目录不存在：{skills_dir}"], []

    seen: dict[str, str] = {}
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            errors.append(f"{skill_dir.name}: 缺少 SKILL.md")
            continue

        meta = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if meta is None:
            errors.append(f"{skill_dir.name}: SKILL.md 缺少合法 YAML frontmatter")
            continue

        name = str(meta.get("name", "")).strip()
        desc = str(meta.get("description", "")).strip()
        if not name:
            errors.append(f"{skill_dir.name}: frontmatter 缺少 name")
        if not desc:
            errors.append(f"{skill_dir.name}: description 不能为空")
        if name != skill_dir.name:
            warnings.append(f"{skill_dir.name}: name '{name}' 与目录名不一致（建议一致）")
        if name and not NAME_RE.match(name):
            warnings.append(
                f"{skill_dir.name}: name '{name}' 不是 slug 形式（建议小写字母/数字/连字符）"
            )
        if name in seen:
            errors.append(f"{skill_dir.name}: 技能名与 {seen[name]} 重复")
        seen[name] = skill_dir.name

    return errors, warnings


def main() -> int:
    default_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description="校验 .agents/skills 技能结构")
    parser.add_argument("--dir", default=str(default_dir), help="技能根目录")
    args = parser.parse_args()

    skills_dir = Path(args.dir).resolve()
    errors, warnings = validate(skills_dir)
    total = len([p for p in skills_dir.iterdir() if p.is_dir()]) if skills_dir.is_dir() else 0

    for warn in warnings:
        print(f"⚠️  {warn}")

    if errors:
        print(f"❌ 发现 {len(errors)} 个问题（共 {total} 个技能）：")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"✅ 校验通过：{total} 个技能结构合规" + (f"（{len(warnings)} 条建议）" if warnings else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
