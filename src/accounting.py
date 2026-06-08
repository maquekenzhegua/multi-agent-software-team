from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class HandoffSpan:
    id: str
    from_role: str
    to_role: str
    message_kind: str
    payload_size: int
    tokens: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class TokenLedger:
    tokens_in: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    tokens_out: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    calls: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record(self, role: str, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in[role] += tokens_in
        self.tokens_out[role] += tokens_out
        self.calls[role] += 1

    def total_for(self, role: str) -> int:
        return self.tokens_in[role] + self.tokens_out[role]

    def grand_total(self) -> int:
        return sum(self.tokens_in.values()) + sum(self.tokens_out.values())


@dataclass
class RunReport:
    issue_url: str
    coders: int
    handoffs: list[HandoffSpan] = field(default_factory=list)
    ledger: TokenLedger = field(default_factory=TokenLedger)
    plan_subtasks: int = 0
    completed_subtasks: int = 0
    reviewer_approved: bool = False
    reviewer_feedback_count: int = 0
    tester_passed: bool = False
    tester_fail_count: int = 0
    merge_conflicts: int = 0
    wall_time_s: float = 0.0
    baseline_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.ledger.grand_total()

    @property
    def handoff_count(self) -> int:
        return len(self.handoffs)

    @property
    def token_amplification(self) -> float:
        if self.baseline_tokens == 0:
            return 0.0
        return self.total_tokens / self.baseline_tokens

    @property
    def tokens_by_role(self) -> dict[str, int]:
        result: dict[str, int] = defaultdict(int)
        for role in set(list(self.ledger.tokens_in.keys()) +
                        list(self.ledger.tokens_out.keys())):
            result[role] = self.ledger.total_for(role)
        return dict(result)

    @property
    def failed_handoffs(self) -> list[HandoffSpan]:
        failures: list[HandoffSpan] = []
        for h in self.handoffs:
            if h.message_kind in ("review_feedback", "test_failed", "replan_needed"):
                failures.append(h)
        return failures

    def summary(self) -> str:
        lines = [
            f"========== 运行报告 ==========",
            f"Issue: {self.issue_url}",
            f"编码者数量: {self.coders}",
            f"子任务: {self.completed_subtasks}/{self.plan_subtasks}",
            f"审查通过: {'是' if self.reviewer_approved else '否'} (反馈 {self.reviewer_feedback_count} 次)",
            f"测试通过: {'是' if self.tester_passed else '否'}",
            f"合并冲突: {self.merge_conflicts}",
            f"总消息交接: {self.handoff_count}",
            f"失败交接: {len(self.failed_handoffs)}",
            f"耗时: {self.wall_time_s:.1f}s",
            f"总 token: {self.total_tokens:,}",
            f"基线 token: {self.baseline_tokens:,}",
            f"Token 放大率: {self.token_amplification:.2f}x",
            f"---------- 各角色 token ----------",
        ]
        for role, n in sorted(self.tokens_by_role.items(), key=lambda x: -x[1]):
            calls = self.ledger.calls.get(role, 0)
            lines.append(f"  {role:16s} {n:>8,} tokens ({calls} 次调用)")
        lines.append("=" * 36)
        return "\n".join(lines)
