"""
XAgent 本地工具单元测试（stdlib unittest，无第三方依赖）。

运行：
    cd agent/XAgent
    python -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import TOOL_MAP, TOOLS_SCHEMA  # noqa: E402
from tools import file_ops, time_ops  # noqa: E402
from core import agents_md  # noqa: E402


class TimeToolsTest(unittest.TestCase):
    def test_current_time_returns_real_clock(self):
        data = json.loads(time_ops.tool_get_current_time({}))
        self.assertRegex(data["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(data["time"], r"^\d{2}:\d{2}:\d{2}$")
        self.assertIn("iso8601", data)

    def test_leap_year_rules(self):
        cases = {2024: True, 2023: False, 1900: False, 2000: True, 2100: False}
        for year, expected in cases.items():
            data = json.loads(time_ops.tool_is_leap_year({"year": year}))
            self.assertEqual(data["isLeapYear"], expected, msg=f"year={year}")

    def test_leap_year_rejects_bad_input(self):
        self.assertIn("error", json.loads(time_ops.tool_is_leap_year({"year": "abc"})))
        self.assertIn("error", json.loads(time_ops.tool_is_leap_year({"year": 0})))

    def test_time_tools_registered(self):
        self.assertIn("getCurrentTime", TOOL_MAP)
        self.assertIn("isLeapYear", TOOL_MAP)
        names = {s["function"]["name"] for s in TOOLS_SCHEMA}
        self.assertTrue({"getCurrentTime", "isLeapYear"} <= names)


class FileOpsTest(unittest.TestCase):
    def setUp(self):
        self.abs_dir = tempfile.mkdtemp(prefix="xagent_test_", dir=file_ops.SANDBOX_ROOT)
        self.rel_dir = os.path.relpath(self.abs_dir, file_ops.SANDBOX_ROOT)

    def tearDown(self):
        shutil.rmtree(self.abs_dir, ignore_errors=True)

    def test_create_read_edit_rename(self):
        self.assertIn("已创建", file_ops.tool_create_file(
            {"dir": self.rel_dir, "filename": "a.txt", "content": "hello"}))
        read_back = file_ops.tool_read_file({"path": f"{self.rel_dir}/a.txt"})
        self.assertIn("hello", read_back)

        file_ops.tool_edit_file(
            {"path": f"{self.rel_dir}/a.txt", "mode": "append", "content": " world"})
        read_back = file_ops.tool_read_file({"path": f"{self.rel_dir}/a.txt"})
        self.assertIn("hello world", read_back)

        file_ops.tool_rename_path(
            {"old_path": f"{self.rel_dir}/a.txt", "new_path": f"{self.rel_dir}/b.txt"})
        self.assertTrue(os.path.isfile(os.path.join(self.abs_dir, "b.txt")))

    def test_delete_requires_confirmation(self):
        file_ops.tool_create_file(
            {"dir": self.rel_dir, "filename": "c.txt", "content": "x"})
        refused = file_ops.tool_delete_file({"path": f"{self.rel_dir}/c.txt"})
        self.assertIn("已拒绝删除", refused)
        self.assertTrue(os.path.isfile(os.path.join(self.abs_dir, "c.txt")))

        ok = file_ops.tool_delete_file(
            {"path": f"{self.rel_dir}/c.txt", "confirm": True})
        self.assertIn("已删除", ok)
        self.assertFalse(os.path.exists(os.path.join(self.abs_dir, "c.txt")))

    def test_path_escape_blocked(self):
        with self.assertRaises(ValueError):
            file_ops.tool_read_file({"path": "../../outside.txt"})


class AgentsMdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="xagent_agents_md_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inject_once_and_truncate(self):
        long_text = "规则" * 8000  # 16000 字符 > 默认 12000
        Path(self.tmp, "AGENTS.md").write_text(long_text, encoding="utf-8")

        messages: list[dict] = [{"role": "system", "content": "sys"}]
        self.assertIsNotNone(agents_md.maybe_inject_agents_md(messages, self.tmp))
        self.assertTrue(agents_md.has_injected_agents_md(messages))
        injected = messages[-1]["content"]
        self.assertIn("已截断", injected)

        # 二次调用不重复注入
        self.assertIsNone(agents_md.maybe_inject_agents_md(messages, self.tmp))
        self.assertEqual(len(messages), 2)

    def test_missing_file_is_silent(self):
        messages: list[dict] = []
        self.assertIsNone(agents_md.maybe_inject_agents_md(messages, self.tmp))
        self.assertEqual(messages, [])


if __name__ == "__main__":
    unittest.main()
