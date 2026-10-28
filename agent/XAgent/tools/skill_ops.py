"""
Skill 操作工具 —— loadSkill。

按需加载某个 Skill 的完整 SKILL.md 正文。
（当前为占位实现：只打印提示，下一步再返回完整内容给 LLM。）
"""
from __future__ import annotations

import json
import sys
from typing import List

from core.skill_loader import discover_skills, load_skill_body, SkillMeta


# 缓存：第一次 discover_skills() 的结果，避免 Agent Loop 每轮都重新扫
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


def tool_load_skill(args: dict) -> str:
    """loadSkill 工具：按需加载指定技能的完整正文。

    当前为占位实现——只通知即将加载，返回简短提示。
    下一步改为返回完整 SKILL.md 内容让 LLM 继续对话。
    """
    skill_name = (args.get("skill_name") or "").strip()

    if not skill_name:
        return json.dumps({
            "exit_code": -1,
            "content": "错误: skill_name 不能为空",
        }, ensure_ascii=False)

    skill = _find_skill(skill_name)
    if skill is None:
        available = ", ".join(f"'{s.name}'" for s in _get_skills()) or "(无)"
        return json.dumps({
            "exit_code": -1,
            "content": f"未找到技能 '{skill_name}'。当前可用技能: {available}",
        }, ensure_ascii=False)

    # 占位：TUI 控制台打印提示
    print(f"[系统] 准备加载技能：{skill_name}  (path={skill.path})", file=sys.stderr, flush=True)

    body = load_skill_body(skill)
    return json.dumps({
        "exit_code": 0,
        "skill_name": skill_name,
        "content": body or "(文件内容为空)",
    }, ensure_ascii=False)


# ========== 工具注册 ==========

SKILL_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "loadSkill",
            "description": (
                "按需加载某个技能的完整指令内容。"
                "当你判断当前用户的任务需要用到某个技能时，调用此工具获取完整规则。"
                "参数 skill_name 必须与技能元数据中的 name 精确匹配。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "要加载的技能名称（与 System Prompt 中列出的名称精确匹配）",
                    },
                },
                "required": ["skill_name"],
                "additionalProperties": False,
            },
        },
    }
]

SKILL_TOOL_MAP = {
    "loadSkill": tool_load_skill,
}
