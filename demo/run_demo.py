#!/usr/bin/env python3
"""一键运行演示：Multi-Agent 团队处理 Task Tracker 项目的 5 个 Issue。

用法:
    python demo/run_demo.py              # stub 模式（无需 API Key）
    python demo/run_demo.py --real        # 真实模式（需要 API Keys）
    python demo/run_demo.py --issue 1     # 只处理第 1 个 Issue
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "demo" / "task-tracker"

ISSUES = [
    {
        "id": 1,
        "title": "添加标签（tag）过滤功能",
        "description": (
            "目前 list_tasks() 只支持按 done 状态过滤，不支持按标签过滤。"
            "需要添加 list_tasks(tag='urgent') 参数，返回包含指定标签的任务。"
            "涉及文件: src/task_tracker/__init__.py, tests/test_task_tracker.py"
        ),
    },
    {
        "id": 2,
        "title": "添加任务优先级（priority）字段",
        "description": (
            "Task 数据类目前只有 id、title、done、tags 四个字段。"
            "需要添加 priority 字段（int, 1-5），add_task 允许指定优先级，"
            "list_tasks 支持按优先级排序。"
            "涉及文件: src/task_tracker/__init__.py, src/task_tracker/cli.py, tests/test_task_tracker.py"
        ),
    },
    {
        "id": 3,
        "title": "添加数据导出功能（JSON/CSV）",
        "description": (
            "任务数据保存在 ~/.task_tracker.json，没有导出功能。"
            "需要添加 export_tasks(format='json') 函数，支持导出为 JSON 或 CSV 格式文件。"
            "涉及文件: src/task_tracker/__init__.py, src/task_tracker/cli.py"
        ),
    },
    {
        "id": 4,
        "title": "修复并发写入导致的数据丢失",
        "description": (
            "save_tasks() 直接写入文件，如果两个进程同时操作会丢失数据。"
            "需要使用文件锁保护写入操作，实现线程安全的持久化。"
            "涉及文件: src/task_tracker/__init__.py"
        ),
    },
    {
        "id": 5,
        "title": "重构 CLI 使用 click 库",
        "description": (
            "CLI 使用 argparse，代码较为冗长。"
            "需要改用 click 库重写 CLI，保持相同的命令行接口。"
            "涉及文件: src/task_tracker/cli.py, requirements.txt"
        ),
    },
]


def setup_demo_repo() -> bool:
    if not (DEMO_DIR / ".git").exists():
        print("初始化 demo git 仓库...")
        subprocess.run(["git", "-C", str(DEMO_DIR), "init"], capture_output=True)
        subprocess.run(["git", "-C", str(DEMO_DIR), "config", "user.email", "demo@team.ai"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(DEMO_DIR), "config", "user.name", "Demo Team"],
                       capture_output=True)
        subprocess.run(["git", "-C", str(DEMO_DIR), "add", "-A"], capture_output=True)
        subprocess.run(["git", "-C", str(DEMO_DIR), "commit", "-m", "initial commit"],
                       capture_output=True)
        return True
    return False


def run_issue(issue: dict, use_stubs: bool) -> dict:
    from src.config import TeamConfig
    from src.orchestrator import TeamRunner
    from src.logging_config import setup_logging

    setup_logging(level="INFO")

    config = TeamConfig.from_env()
    config.board_path = "demo_board.jsonl"
    config.worktree_base = str(DEMO_DIR / ".worktrees")
    config.inject_bug_rate = 0.1

    runner = TeamRunner(config, str(DEMO_DIR), use_stubs=use_stubs)
    report = runner.run(issue["description"])

    return {
        "issue_id": issue["id"],
        "title": issue["title"],
        "plan_subtasks": report.plan_subtasks,
        "completed_subtasks": report.completed_subtasks,
        "reviewer_approved": report.reviewer_approved,
        "tester_passed": report.tester_passed,
        "total_tokens": report.total_tokens,
        "handoffs": report.handoff_count,
        "wall_time_s": report.wall_time_s,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Multi-Agent Team Demo")
    parser.add_argument("--real", action="store_true", help="使用真实 LLM（需要 API Keys）")
    parser.add_argument("--issue", type=int, help="只处理指定 Issue 编号")
    args = parser.parse_args()

    print("=" * 60)
    print("  Multi-Agent Software Engineering Team — 演示")
    print("=" * 60)
    print(f"  项目: Task Tracker CLI")
    print(f"  模式: {'真实 LLM' if args.real else 'Stub（无需 API Key）'}")
    print(f"  Issues: {'全部 5 个' if not args.issue else f'第 {args.issue} 个'}")
    print("=" * 60)

    sys.path.insert(0, str(REPO_ROOT))

    setup_demo_repo()

    target_issues = ISSUES if not args.issue else [i for i in ISSUES if i["id"] == args.issue]
    results = []

    for issue in target_issues:
        print(f"\n--- Issue #{issue['id']}: {issue['title']} ---")
        result = run_issue(issue, use_stubs=not args.real)
        results.append(result)

        print(f"  子任务: {result['completed_subtasks']}/{result['plan_subtasks']}")
        print(f"  审查: {'通过' if result['reviewer_approved'] else '驳回'}")
        print(f"  测试: {'通过' if result['tester_passed'] else '失败'}")
        print(f"  Token: {result['total_tokens']:,}  |  耗时: {result['wall_time_s']:.1f}s")

    print("\n" + "=" * 60)
    print("  演示总结")
    print("=" * 60)
    passed = sum(1 for r in results if r["tester_passed"])
    total_tokens = sum(r["total_tokens"] for r in results)
    total_time = sum(r["wall_time_s"] for r in results)
    print(f"  完成: {passed}/{len(results)} 个 Issue")
    print(f"  总 Token: {total_tokens:,}")
    print(f"  总耗时: {total_time:.1f}s")
    print(f"  平均 Token/Issue: {total_tokens / max(1, len(results)):,.0f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
