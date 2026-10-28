"""验证脚本：打印最终 System Prompt + 工具注册情况。"""
import json
import sys
sys.path.insert(0, ".")

from core.skill_loader import discover_skills, format_skills_for_prompt
from tools import TOOLS_SCHEMA, TOOL_MAP

skills = discover_skills()
block = format_skills_for_prompt(skills)

# 模拟 agent.py 里的 _BASE_SYSTEM_PROMPT
_BASE = (
    "你是一个智能助手，可以调用五类工具："
    "1) 本地文件操作工具；"
    "2) searchWeb 联网搜索工具；"
    "3) fetchWeb 网页抓取工具；"
    "4) runCli 本地命令行执行工具；"
    "5) loadSkill 按需加载技能完整内容。"
    "使用策略：先用 searchWeb 找来源 → fetchWeb 深入 → runCli 系统操作 → loadSkill 加载技能。"
    "工具结果出来后请直接给出自然语言总结，不要输出 JSON 或工具名。"
)
full_prompt = _BASE + block

print("=" * 60)
print("FINAL SYSTEM PROMPT (what gets sent to LLM)")
print("=" * 60)
print(full_prompt)
print("=" * 60)
print()

print(f"Tools registered: {len(TOOLS_SCHEMA)} total")
for t in TOOLS_SCHEMA:
    print(f"  - {t['function']['name']}")
print()

ls = [t for t in TOOLS_SCHEMA if t["function"]["name"] == "loadSkill"][0]
print("loadSkill schema:")
print(json.dumps(ls, ensure_ascii=False, indent=2))
