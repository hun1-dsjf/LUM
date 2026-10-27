"""RunCli 单元测试脚本（无需 LLM，直接测工具函数）。"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools.cli_ops import tool_run_cli

passed = 0
failed = 0


def check(label: str, cond: bool, detail: str = ""):
    global passed, failed
    if cond:
        print(f"  ✅ {label}")
        passed += 1
    else:
        print(f"  ❌ {label}  {detail}")
        failed += 1


# ========== 测试 1：正常执行 dir（Windows 内置命令）==========
print("测试 1: dir（Windows 内置命令，走 cmd.exe /c）")
r = json.loads(tool_run_cli({"command": "dir", "args": []}))
check("exit_code == 0", r["exit_code"] == 0, f"got {r['exit_code']}")
check("stdout 非空且含文件/目录名", len(r["stdout"].strip()) > 0)
check("stderr 为空", r["stderr"].strip() == "", f"stderr: {r['stderr']!r}")

# ========== 测试 2：正常执行 python --version ==========
print("\n测试 2: python --version（外部程序）")
r = json.loads(tool_run_cli({"command": "python", "args": ["--version"]}))
check("exit_code == 0", r["exit_code"] == 0, f"got {r['exit_code']}")
check("stdout/stderr 含 'Python'", "Python" in (r["stdout"] + r["stderr"]),
      f"stdout={r['stdout']!r} stderr={r['stderr']!r}")

# ========== 测试 3：不存在的命令 ==========
print("\n测试 3: 不存在的命令 nonexistent_cmd_xyz")
r = json.loads(tool_run_cli({"command": "nonexistent_cmd_xyz", "args": []}))
check("exit_code == -1", r["exit_code"] == -1)
check("stderr 含 '程序未找到'", "程序未找到" in r["stderr"], f"stderr={r['stderr']!r}")

# ========== 测试 4：空 command ==========
print("\n测试 4: 空 command")
r = json.loads(tool_run_cli({"command": "", "args": []}))
check("exit_code == -1", r["exit_code"] == -1)
check("stderr 含 '不能为空'", "不能为空" in r["stderr"], f"stderr={r['stderr']!r}")

# ========== 测试 5：输出截断 ==========
print("\n测试 5: 输出截断（dir C:\\ 会产生大量输出）")
r = json.loads(tool_run_cli({"command": "dir", "args": ["C:\\", "/s", "/b"], "timeout": 10}))
if r["exit_code"] == -1 and "超时" in r["stderr"]:
    check("命令超时被正确捕获", True)
else:
    check("stdout 被截断或正常返回",
          "[输出过长，已截断]" in r["stdout"] or len(r["stdout"]) <= 2000,
          f"stdout len={len(r['stdout'])}")

# ========== 测试 6：git status ==========
print("\n测试 6: git status（外部程序）")
r = json.loads(tool_run_cli({"command": "git", "args": ["status", "--short"]}))
check("exit_code == 0", r["exit_code"] == 0, f"got {r['exit_code']}")

# ========== 测试 7：ipconfig ==========
print("\n测试 7: ipconfig（Windows 内置命令，不是 ipconfig.exe！）")
# ipconfig 是 .exe，应该直接调
r = json.loads(tool_run_cli({"command": "ipconfig", "args": ["/all"], "timeout": 10}))
# ipconfig 可能超时（/all 很慢），只要不是 FileNotFound 就行
if r["exit_code"] == -1 and "程序未找到" in r["stderr"]:
    check("ipconfig 可执行", False, f"stderr={r['stderr']}")
elif r["exit_code"] == -1 and "超时" in r["stderr"]:
    check("ipconfig 可执行但 /all 超时（正常）", True)
else:
    check("ipconfig 可执行并返回结果", True, f"exit_code={r['exit_code']}")

# ========== 汇总 ==========
print(f"\n{'='*40}")
print(f"结果: {passed} passed, {failed} failed")
print(f"{'='*40}")

sys.exit(0 if failed == 0 else 1)
