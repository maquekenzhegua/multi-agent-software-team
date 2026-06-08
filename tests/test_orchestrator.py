from __future__ import annotations

import os
import tempfile
import subprocess

from src.config import TeamConfig
from src.task_board import Board
from src.orchestrator import TeamRunner


def setup_test_repo(path: str) -> None:
    subprocess.run(["git", "-C", path, "init"], capture_output=True)
    subprocess.run(["git", "-C", path, "config", "user.email", "bot@team.ai"],
                   capture_output=True)
    subprocess.run(["git", "-C", path, "config", "user.name", "Agent Team"],
                   capture_output=True)
    os.makedirs(os.path.join(path, "src"), exist_ok=True)
    os.makedirs(os.path.join(path, "tests"), exist_ok=True)
    open(os.path.join(path, "src", "__init__.py"), "w").close()
    open(os.path.join(path, "src", "parser.py"), "w").write(
        "def parse(s):\n    return s.split()\n")
    open(os.path.join(path, "src", "cache.py"), "w").write(
        "class Cache:\n    def get(self, k):\n        return None\n")
    open(os.path.join(path, "src", "api.py"), "w").write(
        "def handle(req):\n    return {'status': 'ok'}\n")
    open(os.path.join(path, "src", "migrate.py"), "w").write(
        "def migrate():\n    pass\n")
    subprocess.run(["git", "-C", path, "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", path, "commit", "-m", "initial scaffold"],
                   capture_output=True)


def test_team_run_stub():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        setup_test_repo(tmpdir)
        config = TeamConfig()
        config.board_path = "board.jsonl"
        config.worktree_base = os.path.join(tmpdir, "worktrees")

        runner = TeamRunner(config, tmpdir, use_stubs=True)
        report = runner.run("fix widget parser race condition", n_coders=2)

        assert report.plan_subtasks > 0
        assert report.completed_subtasks > 0
        assert report.reviewer_approved
        assert report.tester_passed
        assert report.total_tokens > 0
        assert report.handoff_count > 0
        assert report.wall_time_s > 0
        assert len(report.tokens_by_role) >= 2

        summary = report.summary()
        assert "运行报告" in summary
        assert "Token 放大率" in summary


def test_single_agent_baseline():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        setup_test_repo(tmpdir)
        config = TeamConfig()
        config.worktree_base = os.path.join(tmpdir, "worktrees")

        runner = TeamRunner(config, tmpdir, use_stubs=True)
        report = runner.single_agent_baseline("fix parser")

        assert report.plan_subtasks == 1
        assert report.completed_subtasks == 1
        assert report.total_tokens > 0


def test_eval_swebench():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        setup_test_repo(tmpdir)
        config = TeamConfig()
        config.board_path = "board.jsonl"
        config.worktree_base = os.path.join(tmpdir, "worktrees")

        runner = TeamRunner(config, tmpdir, use_stubs=True)
        results = runner.eval_swebench(
            ["issue-1: fix cache overflow", "issue-2: add logging"],
            n_coders=2, baseline=True,
        )

        assert len(results["team"]) == 2
        assert len(results["baseline"]) == 2
        assert results["summary"]["issues"] == 2
        assert results["summary"]["team_pass_rate"] >= 0


def test_report_token_amplification():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        setup_test_repo(tmpdir)
        config = TeamConfig()
        config.board_path = "board.jsonl"
        config.worktree_base = os.path.join(tmpdir, "worktrees")

        runner = TeamRunner(config, tmpdir, use_stubs=True)
        report = runner.run("test issue", n_coders=3)
        bl = runner.single_agent_baseline("test issue")
        report.baseline_tokens = bl.total_tokens

        assert report.baseline_tokens > 0
        assert report.token_amplification > 0
        assert report.failed_handoffs is not None


def test_e2e_with_all_roles_exercised():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        setup_test_repo(tmpdir)
        board_path = os.path.join(tmpdir, "board.jsonl")
        config = TeamConfig()
        config.board_path = "board.jsonl"
        config.worktree_base = os.path.join(tmpdir, "worktrees")

        runner = TeamRunner(config, tmpdir, use_stubs=True)
        report = runner.run("complex issue: refactor entire API layer", n_coders=4)

        assert report.plan_subtasks == 4
        assert report.completed_subtasks == 4
        role_tokens = report.tokens_by_role
        assert "architect" in role_tokens or any("coder" in r for r in role_tokens)

        assert report.handoff_count >= 4
        assert report.reviewer_approved
        assert report.tester_passed
