from __future__ import annotations

import json

from src.config import TeamConfig
from src.roles.architect import Architect, create_stub_architect
from src.roles.coder import Coder, create_stub_coder
from src.roles.merge_coord import MergeCoordinator
from src.roles.reviewer import Reviewer, create_stub_reviewer
from src.roles.tester import Tester, create_stub_tester


def test_architect_stub_plan():
    architect = create_stub_architect()
    summary, subtasks, response = architect.run("修复 widget 解析竞态条件")
    assert len(summary) > 0
    assert len(subtasks) == 4
    assert subtasks[0].name == "lock"
    assert "files" in subtasks[0].to_dict()
    assert response.total_tokens > 0


def test_architect_parse_json_response():
    architect = create_stub_architect()
    content = '''```json
{
  "summary": "修复缓存并发Bug",
  "subtasks": [
    {"name": "lock", "description": "添加锁机制", "files": ["src/lock.py"], "interfaces": ["acquire()"], "dependencies": []},
    {"name": "test", "description": "并发测试", "files": ["tests/test_lock.py"], "interfaces": [], "dependencies": ["lock"]}
  ]
}
```'''
    result = architect._parse_response(content)
    assert result["summary"] == "修复缓存并发Bug"
    assert len(result["subtasks"]) == 2
    assert result["subtasks"][1]["dependencies"] == ["lock"]


def test_architect_fallback_parse():
    architect = create_stub_architect()
    content = '''summary: 修复问题
{
  "name": "parser",
  "description": "修复解析器",
  "files": ["src/parser.py"]
}
{
  "name": "api",
  "description": "API更新",
  "files": ["src/api.py"]
}'''
    result = architect._regex_parse(content)
    assert "subtasks" in result


def test_coder_stub():
    import subprocess as sp
    coder = create_stub_coder("coder-A")
    from src.roles.architect import Subtask
    sub = Subtask(name="parser", description="修复解析器",
                  files=["src/parser.py"], interfaces=["parse(s: str) -> dict"])
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        os.makedirs(os.path.join(tmpdir, "src"), exist_ok=True)
        open(os.path.join(tmpdir, "src", "parser.py"), "w").write("# old\n")
        sp.run(["git", "-C", tmpdir, "init"], capture_output=True)
        sp.run(["git", "-C", tmpdir, "config", "user.email", "bot@test.com"],
               capture_output=True)
        sp.run(["git", "-C", tmpdir, "config", "user.name", "TestBot"],
               capture_output=True)
        sp.run(["git", "-C", tmpdir, "add", "-A"], capture_output=True)
        sp.run(["git", "-C", tmpdir, "commit", "-m", "init"], capture_output=True)
        wt_base = os.path.join(tmpdir, "worktrees")
        result = coder.run(sub, tmpdir, wt_base)
        assert result.subtask_name == "parser"
        assert result.lines_added >= 0


def test_reviewer_stub_approve():
    reviewer = create_stub_reviewer()
    result = reviewer.run(
        patch="diff --git a/src/test.py b/src/test.py\n+def foo(): pass",
        subtask_names=["test"],
        authors=["coder-Z"],
    )
    assert result.approved


def test_reviewer_self_review_blocked():
    reviewer = create_stub_reviewer()
    result = reviewer.run(
        patch="diff content",
        subtask_names=["test"],
        authors=["coder-Z"],
    )
    assert result.approved
    reviewer.run(patch="diff", subtask_names=["test"], authors=["coder-Z"])
    result3 = reviewer.run(
        patch="other diff",
        subtask_names=["other"],
        authors=["coder-Z"],
    )
    assert not result3.approved


def test_reviewer_inject_bug_detection():
    reviewer = create_stub_reviewer()
    result = reviewer.run(
        patch="""diff --git a/src/main.py b/src/main.py
+def calculate_total(items):
+    total = 0
+    for i in range(len(items) - 1):
+        total += items[i]
+    return total""",
        subtask_names=["main"],
        authors=["coder-X"],
        inject_known_bug=True,
    )
    assert result.false_approve


def test_tester_stub():
    tester = create_stub_tester()
    import tempfile, os
    with tempfile.TemporaryDirectory() as tmpdir:
        result = tester.run(tmpdir, test_command="echo ok")
        assert result.passed


def test_merge_coord_stub():
    from src.llm import StubLLMClient
    config = TeamConfig()
    merger = MergeCoordinator(config, StubLLMClient())
    import tempfile, os, subprocess
    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "-C", tmpdir, "init"], capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "config", "user.email", "test@test.com"],
                       capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "config", "user.name", "Test"],
                       capture_output=True)
        open(os.path.join(tmpdir, "readme.md"), "w").write("# test")
        subprocess.run(["git", "-C", tmpdir, "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", tmpdir, "commit", "-m", "init"], capture_output=True)


def subprocess_run(cmd, capture_output):
    import subprocess
    try:
        return subprocess.run(cmd, capture_output=capture_output, timeout=10)
    except Exception:
        pass
