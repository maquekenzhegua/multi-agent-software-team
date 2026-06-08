#!/usr/bin/env python3
"""多 Agent 软件工程团队 — 命令行入口

用法:
    python cli.py run --issue <url> [--repo <path>] [--coders N] [--stub]
    python cli.py eval --issues-file <path> [--coders N] [--baseline] [--stub]
    python cli.py baseline --issue <url> [--repo <path>] [--stub]

示例:
    python cli.py run --issue "修复 widget 解析竞态条件" --stub
    python cli.py eval --issues-file issues.txt --coders 4 --stub
    python cli.py baseline --issue "修复 parser bug" --stub
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.config import TeamConfig
from src.logging_config import setup_logging
from src.orchestrator import TeamRunner


def cmd_run(args: argparse.Namespace) -> None:
    setup_logging(level="DEBUG" if args.verbose else "INFO",
                  log_file=args.log_file)
    config = TeamConfig.from_env()
    if args.stub:
        import src.llm as llm_mod
        llm_mod.LLMFactory.reset()

    repo_path = args.repo or os.getcwd()
    issue_text = args.issue

    if issue_text.startswith("http"):
        from src.roles.architect import Architect
        issue_text = Architect.fetch_issue(args.issue)

    runner = TeamRunner(config, repo_path, use_stubs=args.stub)
    report = runner.run(issue_text, n_coders=args.coders or config.default_coders)

    if args.baseline:
        bl = runner.single_agent_baseline(issue_text)
        report.baseline_tokens = bl.total_tokens
        print(f"\n[基线] 单 Agent: {bl.total_tokens:,} tokens")

    print()
    print(report.summary())

    if args.output:
        data = {
            "issue": args.issue,
            "tester_passed": report.tester_passed,
            "reviewer_approved": report.reviewer_approved,
            "total_tokens": report.total_tokens,
            "tokens_by_role": report.tokens_by_role,
            "handoff_count": report.handoff_count,
            "token_amplification": report.token_amplification,
            "wall_time_s": report.wall_time_s,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"报告已写入: {args.output}")


def cmd_eval(args: argparse.Namespace) -> None:
    config = TeamConfig.from_env()
    repo_path = args.repo or os.getcwd()

    with open(args.issues_file, "r", encoding="utf-8") as f:
        issues = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    print(f"加载 {len(issues)} 个 Issue\n")

    runner = TeamRunner(config, repo_path, use_stubs=args.stub)
    results = runner.eval_swebench(
        issues, n_coders=args.coders or config.default_coders,
        baseline=args.baseline,
    )

    s = results["summary"]
    print()
    print("=" * 50)
    print("          评估结果汇总")
    print("=" * 50)
    print(f"Issues 数量:   {s['issues']}")
    print(f"团队通过:      {s['team_pass']}/{s['issues']} ({s['team_pass_rate']:.0%})")
    if results["baseline"]:
        print(f"基线通过:      {s['baseline_pass']}/{s['issues']}")
        amp = s['avg_tokens_team'] / max(1, s['avg_tokens_baseline'])
        print(f"平均 Token:    团队 {s['avg_tokens_team']:,.0f}  vs  基线 {s['avg_tokens_baseline']:,.0f}  ({amp:.2f}x)")
    print("=" * 50)

    if args.output:
        out = {
            "summary": s,
            "team_reports": [
                {"issue": r.issue_url, "passed": r.tester_passed,
                 "tokens": r.total_tokens, "time": r.wall_time_s}
                for r in results["team"]
            ],
        }
        if results["baseline"]:
            out["baseline_reports"] = [
                {"issue": r.issue_url, "passed": r.tester_passed,
                 "tokens": r.total_tokens, "time": r.wall_time_s}
                for r in results["baseline"]
            ]
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"评估报告已写入: {args.output}")


def cmd_baseline(args: argparse.Namespace) -> None:
    config = TeamConfig.from_env()
    repo_path = args.repo or os.getcwd()
    issue_text = args.issue
    if issue_text.startswith("http"):
        from src.roles.architect import Architect
        issue_text = Architect.fetch_issue(args.issue)

    runner = TeamRunner(config, repo_path, use_stubs=args.stub)
    report = runner.single_agent_baseline(issue_text)
    print()
    print(report.summary())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="多 Agent 软件工程团队",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="运行团队处理单个 Issue")
    p_run.add_argument("--issue", required=True, help="GitHub Issue URL 或问题描述")
    p_run.add_argument("--repo", help="仓库路径（默认当前目录）")
    p_run.add_argument("--coders", type=int, help="并行编码者数量（默认 4）")
    p_run.add_argument("--baseline", action="store_true", help="同时运行单 Agent 基线")
    p_run.add_argument("--stub", action="store_true", help="使用 stub LLM 进行测试")
    p_run.add_argument("--output", help="报告输出 JSON 路径")
    p_run.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    p_run.add_argument("--log-file", help="日志文件路径")
    p_run.set_defaults(func=cmd_run)

    p_eval = sub.add_parser("eval", help="批量评估（SWE-bench 模式）")
    p_eval.add_argument("--issues-file", required=True, help="每行一个 Issue 的文件")
    p_eval.add_argument("--repo", help="仓库路径")
    p_eval.add_argument("--coders", type=int, help="并行编码者数量")
    p_eval.add_argument("--baseline", action="store_true", help="运行单 Agent 基线对比")
    p_eval.add_argument("--stub", action="store_true", help="使用 stub LLM 进行测试")
    p_eval.add_argument("--output", help="评估报告输出 JSON 路径")
    p_eval.set_defaults(func=cmd_eval)

    p_bl = sub.add_parser("baseline", help="运行单 Agent 基线")
    p_bl.add_argument("--issue", required=True, help="GitHub Issue URL 或问题描述")
    p_bl.add_argument("--repo", help="仓库路径")
    p_bl.add_argument("--stub", action="store_true", help="使用 stub LLM 进行测试")
    p_bl.set_defaults(func=cmd_baseline)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
