"""验证 loadSkill 的 3 个核心场景。"""
import json
import sys
sys.path.insert(0, ".")

from tools.skill_ops import tool_load_skill

# 场景 1：仅传 name → SKILL.md 正文（frontmatter 已剥离）
print("=" * 60)
print("场景 1: 仅 name='撰写通知' → SKILL.md 正文")
print("=" * 60)
r = json.loads(tool_load_skill({"name": "撰写通知"}))
print(f"exit_code: {r['exit_code']}")
print(f"skill_name: {r.get('skill_name')}")
print(f"skill_dir: {r.get('skill_dir')}")
print(f"file: {r.get('file')}")
print(f"content (前 300 字符):\n{r.get('content', r.get('error', ''))[:300]}")
assert r["exit_code"] == 0, f"期望 exit_code=0, 实际 {r['exit_code']}"
assert 'content' in r and '---' not in r.get('content', '')[:20], "frontmatter 应被剥离"
print("✅ PASS")

# 场景 2：路径穿越攻击 → 被拦截
print()
print("=" * 60)
print("场景 2: 越权 filename='../../../.env'")
print("=" * 60)
r = json.loads(tool_load_skill({"name": "撰写通知", "filename": "../../../.env"}))
print(f"exit_code: {r['exit_code']}")
print(f"error: {r.get('error')}")
assert r["exit_code"] == -1
assert "安全拦截" in r.get("error", "") or "不存在" in r.get("error", "")
print("✅ PASS")

# 场景 3：纯文件名 filename='test.md' → 递归搜索
print()
print("=" * 60)
print("场景 3: filename='test.md' (纯文件名递归搜索)")
print("=" * 60)
r = json.loads(tool_load_skill({"name": "撰写通知", "filename": "test.md"}))
print(f"exit_code: {r['exit_code']}")
print(f"file: {r.get('file')}")
print(f"content: {r.get('content', r.get('error', ''))}")
assert r["exit_code"] == 0
assert r.get("file") == "test.md"
print("✅ PASS")

# 场景 4：技能不存在
print()
print("=" * 60)
print("场景 4: 技能不存在 'xxx'")
print("=" * 60)
r = json.loads(tool_load_skill({"name": "不存在的技能"}))
print(f"exit_code: {r['exit_code']}")
print(f"error: {r.get('error')}")
assert r["exit_code"] == -1
print("✅ PASS")

# 场景 5：filename 不存在
print()
print("=" * 60)
print("场景 5: 文件名不存在 'nope.md'")
print("=" * 60)
r = json.loads(tool_load_skill({"name": "撰写通知", "filename": "nope.md"}))
print(f"exit_code: {r['exit_code']}")
print(f"error: {r.get('error')}")
assert r["exit_code"] == -1
print("✅ PASS")

print()
print("=" * 60)
print("ALL 5 SCENARIOS PASSED 🎉")
print("=" * 60)
