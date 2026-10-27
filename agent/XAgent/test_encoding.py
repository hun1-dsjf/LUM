"""编码修复验证：跑 dir 和 tasklist，检查中文是否正常显示。"""
import json
import locale
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.cli_ops import tool_run_cli

print(f"系统首选编码: {locale.getpreferredencoding(False)}")
print(f"Python stdout 编码: {sys.stdout.encoding}")
print()

# 测试 1: dir（目录列表会有中文文件夹名）
print("=" * 50)
print("测试 1: dir XAgent 目录")
print("=" * 50)
r = json.loads(tool_run_cli({"command": "dir", "args": []}))
print(f"exit_code: {r['exit_code']}")
print("--- stdout 前 500 字符 ---")
print(r["stdout"][:500])
print("--- 检查乱码 ---")
has_garbled = "\\u" in r["stdout"][:500] or "?" * 3 in r["stdout"][:500]
print(f"是否存在 \\uXXXX 形式的转义: {'\\u' in r['stdout'][:500]}")
print(f"是否存在大量 ? 问号: {'???' in r['stdout'][:500]}")
print()

# 测试 2: tasklist
print("=" * 50)
print("测试 2: tasklist")
print("=" * 50)
r = json.loads(tool_run_cli({"command": "tasklist", "args": ["/FI", "IMAGENAME eq python.exe"]}))
print(f"exit_code: {r['exit_code']}")
print("--- stdout ---")
print(r["stdout"][:800])
print()

# 测试 3: git log（git 输出 UTF-8，验证 UTF-8 也能正确处理）
print("=" * 50)
print("测试 3: git log（UTF-8 输出验证）")
print("=" * 50)
import subprocess
result = subprocess.run(["git", "log", "--oneline", "-3"], capture_output=True)
print(f"raw bytes sample: {result.stdout[:80]}")
r = json.loads(tool_run_cli({"command": "git", "args": ["log", "--oneline", "-3"]}))
print(f"exit_code: {r['exit_code']}")
print("--- stdout ---")
print(r["stdout"])
print()

print("✅ 编码验证完成")
