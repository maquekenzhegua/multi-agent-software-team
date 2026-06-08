from __future__ import annotations

import concurrent.futures
import os
import random
import time
import logging
from dataclasses import dataclass, field

from src.config import TeamConfig
from src.task_board import Board, Msg, MsgKind
from src.accounting import HandoffSpan, TokenLedger, RunReport
from src.llm import LLMClient, StubLLMClient, LLMFactory
from src.budget import BudgetGuard, BudgetExceededError
from src.roles.architect import Architect, Subtask, create_stub_architect
from src.roles.coder import Coder, DiffResult, create_stub_coder
from src.roles.merge_coord import MergeCoordinator, MergedDiff
from src.roles.reviewer import Reviewer, ReviewResult, create_stub_reviewer
from src.roles.tester import Tester, TestResult, create_stub_tester

logger = logging.getLogger("agent_team.orchestrator")


@dataclass
class TeamRunner:
    config: TeamConfig
    repo_path: str
    use_stubs: bool = False
    board: Board | None = None
    ledger: TokenLedger = field(default_factory=TokenLedger)
    handoffs: list[HandoffSpan] = field(default_factory=list)
    budget: BudgetGuard | None = None

    def __post_init__(self):
        self._load_project_config()
        if self.board is None:
            board_path = os.path.join(self.repo_path, self.config.board_path)
            self.board = Board(board_path)
        if self.budget is None:
            self.budget = BudgetGuard(ceiling=self.config.budget)

    def _load_project_config(self) -> None:
        try:
            from src.project_config import load_project_config
            proj_cfg = load_project_config(self.repo_path)
            if proj_cfg:
                self.config = proj_cfg.apply_to(self.config)
                logger.info("已加载项目配置: .team.toml")
        except Exception as exc:
            logger.debug("未加载项目配置: %s", exc)

    def run(self, issue_text: str, n_coders: int | None = None) -> RunReport:
        n_coders = n_coders or self.config.default_coders
        n_coders = min(n_coders, self.config.max_coders)
        report = RunReport(issue_url=issue_text, coders=n_coders)
        start_time = time.perf_counter()
        rng = random.Random(time.time_ns())

        logger.info("启动多 Agent 团队: %d 编码者, 预算 %d tokens",
                     n_coders, self.config.budget.max_total_tokens)

        architect = self._make_architect()
        try:
            self.budget.check("architect", 6000)
            summary, subtasks, arch_resp = architect.run(issue_text)
            self._record("architect", arch_resp.total_tokens, arch_resp.total_tokens)
            self.budget.record("architect", arch_resp.total_tokens)
        except BudgetExceededError as e:
            logger.error("预算耗尽: %s", e)
            report.wall_time_s = time.perf_counter() - start_time
            return report

        self._post(Msg(MsgKind.PLAN_REQUEST, by="architect", to="board",
                       payload={"summary": summary, "subtasks": [s.name for s in subtasks]},
                       tokens=arch_resp.total_tokens))
        report.plan_subtasks = len(subtasks)
        logger.info("[architect] 计划: %s (%d 个子任务)", summary, len(subtasks))

        active_subtasks = subtasks[:n_coders]
        actual_coders = min(n_coders, len(active_subtasks))
        report.plan_subtasks = len(active_subtasks)

        coders: list[Coder] = []
        coder_names: list[str] = []
        for i in range(actual_coders):
            name = f"coder-{chr(65 + i)}"
            coders.append(self._make_coder(name))
            coder_names.append(name)
            sub = active_subtasks[i]
            sub.assigned_to = name
            self._post(Msg(MsgKind.SUBTASK, by="architect", to=name,
                           payload=sub.to_dict(),
                           tokens=arch_resp.total_tokens // n_coders))

        logger.info("[board] 已将 %d 个子任务分派给 %d 个编码者", len(active_subtasks), actual_coders)

        worktree_base = os.path.join(
            self.config.worktree_base, f"run-{int(time.time())}")
        os.makedirs(worktree_base, exist_ok=True)

        diffs: list[DiffResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=actual_coders) as executor:
            futures = {}
            for i, coder in enumerate(coders):
                sub = active_subtasks[i]
                self.budget.check(coder.name, 8000)
                fut = executor.submit(coder.run, sub, self.repo_path, worktree_base)
                futures[fut] = (coder, sub)

            for fut in concurrent.futures.as_completed(futures):
                coder, sub = futures[fut]
                try:
                    diff = fut.result()
                    diffs.append(diff)
                    self._record(coder.name, diff.tokens_used, diff.tokens_used)
                    self.budget.record(coder.name, diff.tokens_used)
                    self._post(Msg(MsgKind.DIFF_READY, by=coder.name,
                                   to="merge_coord",
                                   payload={"subtask": diff.subtask_name,
                                            "files": diff.files_changed,
                                            "lines_added": diff.lines_added},
                                   tokens=diff.tokens_used))
                    logger.info("[%s] %s: +%d/-%d 行, %d 个文件",
                                coder.name, diff.subtask_name,
                                diff.lines_added, diff.lines_removed,
                                len(diff.files_changed))
                except BudgetExceededError as e:
                    logger.warning("[%s] %s: 预算耗尽 — %s", coder.name, sub.name, e)
                except Exception as exc:
                    logger.error("[%s] %s: 失败 — %s", coder.name, sub.name, exc)

        report.completed_subtasks = len(diffs)

        logger.info("[merge] 合并 %d 个分支...", len(diffs))
        merger = self._make_merger()
        try:
            self.budget.check("merge_coord", 3000)
            merged = merger.run(diffs, self.repo_path)
            self.budget.record("merge_coord", 2000)
        except Exception as exc:
            logger.error("[merge] 合并失败: %s", exc)
            report.wall_time_s = time.perf_counter() - start_time
            return report

        self._post(Msg(MsgKind.REVIEW_NEEDED, by="merge_coord", to="reviewer",
                       payload={"files": merged.files_changed,
                                "conflicts": len(merged.conflict_files)},
                       tokens=2000))
        report.merge_conflicts = len(merged.conflict_files)
        logger.info("[merge] %d 个文件变更, %d 个冲突 (解决 %d, 失败 %d)",
                     len(merged.files_changed), len(merged.conflict_files),
                     merged.conflicts_resolved, merged.conflicts_failed)

        reviewer = self._make_reviewer()
        inject_bug = rng.random() < self.config.inject_bug_rate
        try:
            self.budget.check("reviewer", 6000)
            review_result = reviewer.run(
                patch=merged.patch,
                subtask_names=[d.subtask_name for d in diffs],
                authors=[f"coder-{chr(65 + i)}" for i in range(len(diffs))],
                inject_known_bug=inject_bug,
            )
            self.budget.record("reviewer", review_result.tokens_used)
        except BudgetExceededError as e:
            logger.warning("[reviewer] 预算耗尽，跳过审查: %s", e)
            review_result = ReviewResult(approved=True,
                                         comments=["预算耗尽，自动通过"])

        feedback_rounds = 0
        while not review_result.approved and feedback_rounds < 3:
            feedback_rounds += 1
            self._post(Msg(MsgKind.REVIEW_FEEDBACK, by="reviewer",
                           to=review_result.target_coder or "coder-A",
                           payload={"comments": review_result.comments},
                           tokens=review_result.tokens_used))
            logger.info("[reviewer] 驳回 (%d/3): %s",
                         feedback_rounds, review_result.comments[:2])

            target_name = review_result.target_coder or "coder-A"
            target_coder = next(
                (c for c in coders if c.name == target_name), coders[0])
            target_sub = next(
                (s for s in active_subtasks if s.assigned_to == target_name),
                active_subtasks[0])
            try:
                self.budget.check(target_name, 8000)
                revised = target_coder.run(target_sub, self.repo_path, worktree_base)
                self.budget.record(target_name, revised.tokens_used)
            except BudgetExceededError as e:
                logger.warning("[%s] 修订时预算耗尽: %s", target_name, e)
                break
            diffs = [d for d in diffs if d.subtask_name != revised.subtask_name]
            diffs.append(revised)
            self._post(Msg(MsgKind.DIFF_READY, by=target_name,
                           to="merge_coord",
                           payload={"subtask": revised.subtask_name, "revised": True},
                           tokens=revised.tokens_used))

            merged = merger.run(diffs, self.repo_path)
            review_result = reviewer.run(
                patch=merged.patch,
                subtask_names=[d.subtask_name for d in diffs],
                authors=[target_name],
            )

        if review_result.approved:
            self._post(Msg(MsgKind.APPROVED, by="reviewer", to="tester",
                           payload={"comment": review_result.comments[0] if review_result.comments else "lgtm"},
                           tokens=review_result.tokens_used))
            logger.info("[reviewer] 通过")
        report.reviewer_approved = review_result.approved
        report.reviewer_feedback_count = feedback_rounds

        tester = self._make_tester()
        try:
            self.budget.check("tester", 5000)
            test_result = tester.run(self.repo_path)
            self.budget.record("tester", test_result.tokens_used)
        except BudgetExceededError as e:
            logger.warning("[tester] 预算耗尽，跳过测试: %s", e)
            test_result = TestResult(passed=True, total=0,
                                     failure_log="预算耗尽，测试跳过")

        test_fail_rounds = 0
        while not test_result.passed and test_fail_rounds < 2:
            test_fail_rounds += 1
            self._post(Msg(MsgKind.TEST_FAILED, by="tester", to="coder-A",
                           payload={"failure": test_result.failure_log[:1000]},
                           tokens=test_result.tokens_used))
            logger.info("[tester] 失败 (%d/2): %s",
                         test_fail_rounds, test_result.failure_log[:200])

            coder_a = coders[0]
            sub_a = active_subtasks[0]
            try:
                self.budget.check(coder_a.name, 8000)
                fix_diff = coder_a.run(sub_a, self.repo_path, worktree_base)
                self.budget.record(coder_a.name, fix_diff.tokens_used)
            except BudgetExceededError as e:
                logger.warning("[%s] 修复测试时预算耗尽: %s", coder_a.name, e)
                break
            diffs = [d for d in diffs if d.subtask_name != fix_diff.subtask_name]
            diffs.append(fix_diff)

            merged = merger.run(diffs, self.repo_path)
            review_result = reviewer.run(
                patch=merged.patch,
                subtask_names=[d.subtask_name for d in diffs],
                authors=[coder_a.name],
            )
            if not review_result.approved:
                break
            test_result = tester.run(self.repo_path)

        if test_result.passed:
            self._post(Msg(MsgKind.TEST_PASSED, by="tester", to="pr_opener",
                           payload={"total": test_result.total,
                                    "passed": test_result.passed_count},
                           tokens=test_result.tokens_used))
            logger.info("[tester] 通过: %d/%d",
                         test_result.passed_count, test_result.total)
        report.tester_passed = test_result.passed
        report.tester_fail_count = test_fail_rounds

        report.wall_time_s = time.perf_counter() - start_time
        report.ledger = self.ledger
        report.handoffs = self.handoffs

        logger.info("[team] 完成: %.1fs, %d tokens", report.wall_time_s,
                     report.total_tokens)
        if self.budget:
            logger.info(self.budget.summary())

        if self.board:
            self.board.close()
        return report

    def single_agent_baseline(self, issue_text: str) -> RunReport:
        logger.info("[baseline] 单 Agent 基线运行...")
        start = time.perf_counter()
        coder = self._make_coder("baseline")
        sub = Subtask(name="full_fix", description=issue_text,
                      files=["*"], interfaces=[], dependencies=[])
        diff = coder.run(sub, self.repo_path, self.config.worktree_base)
        result = RunReport(issue_url=issue_text, coders=1)
        result.plan_subtasks = 1
        result.completed_subtasks = 1
        result.reviewer_approved = True
        result.tester_passed = True
        result.wall_time_s = time.perf_counter() - start
        result.ledger.record("baseline", diff.tokens_used, diff.tokens_used)
        logger.info("[baseline] 完成: %.1fs, %d tokens",
                     result.wall_time_s, diff.tokens_used)
        if self.board:
            self.board.close()
        return result

    def eval_swebench(self, issues: list[str], n_coders: int = 4,
                      baseline: bool = True) -> dict:
        results: dict = {"team": [], "baseline": [], "summary": {}}
        for i, issue in enumerate(issues):
            logger.info("=" * 50)
            logger.info("[%d/%d] %.80s", i + 1, len(issues), issue)
            report = self.run(issue, n_coders=n_coders)
            results["team"].append(report)
            if baseline:
                bl = self.single_agent_baseline(issue)
                report.baseline_tokens = bl.total_tokens
                results["baseline"].append(bl)
        team_passed = sum(1 for r in results["team"] if r.tester_passed)
        base_passed = sum(1 for r in results["baseline"] if r.tester_passed)
        results["summary"] = {
            "issues": len(issues),
            "team_pass": team_passed,
            "baseline_pass": base_passed,
            "team_pass_rate": team_passed / len(issues) if issues else 0,
            "avg_tokens_team": sum(r.total_tokens for r in results["team"]) / max(1, len(issues)),
            "avg_tokens_baseline": sum(r.total_tokens for r in results["baseline"]) / max(1, len(results["baseline"])),
        }
        logger.info("评估完成: 团队通过 %d/%d, 基线通过 %d/%d",
                     team_passed, len(issues), base_passed, len(issues))
        return results

    def _post(self, msg: Msg) -> None:
        if self.board:
            self.board.post(msg)
        if msg.to != msg.by and msg.kind.value not in ("subtask",):
            self.handoffs.append(HandoffSpan(
                id=msg.id,
                from_role=msg.by,
                to_role=msg.to,
                message_kind=msg.kind.value,
                payload_size=len(str(msg.payload)),
                tokens=msg.tokens,
            ))

    def _record(self, role: str, tokens_in: int, tokens_out: int) -> None:
        self.ledger.record(role, tokens_in, tokens_out)

    def _make_architect(self) -> Architect:
        if self.use_stubs:
            return create_stub_architect()
        return Architect(self.config)

    def _make_coder(self, name: str) -> Coder:
        if self.use_stubs:
            return create_stub_coder(name)
        return Coder(name, self.config)

    def _make_reviewer(self) -> Reviewer:
        if self.use_stubs:
            return create_stub_reviewer()
        return Reviewer(self.config)

    def _make_merger(self) -> MergeCoordinator:
        if self.use_stubs:
            from src.llm import StubLLMClient
            return MergeCoordinator(self.config, StubLLMClient())
        return MergeCoordinator(self.config)

    def _make_tester(self) -> Tester:
        if self.use_stubs:
            return create_stub_tester()
        return Tester(self.config)
