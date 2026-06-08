from __future__ import annotations

import logging
from dataclasses import dataclass, field

from src.config import BudgetCeiling

logger = logging.getLogger("agent_team.budget")


class BudgetExceededError(Exception):
    def __init__(self, role: str, current: int, limit: int,
                 total_current: int = 0, total_limit: int = 0):
        self.role = role
        self.current = current
        self.limit = limit
        self.total_current = total_current
        self.total_limit = total_limit
        msg = (f"[预算耗尽] {role}: 已用 {current:,}/{limit:,} tokens")
        if total_limit > 0:
            msg += f" (总计 {total_current:,}/{total_limit:,})"
        super().__init__(msg)


@dataclass
class BudgetGuard:
    ceiling: BudgetCeiling
    spent_per_role: dict[str, int] = field(default_factory=dict)
    total_spent: int = 0

    def check(self, role: str, estimated_tokens: int) -> None:
        role_limit = self.ceiling.max_tokens_per_role.get(role, 20000)
        role_spent = self.spent_per_role.get(role, 0)
        projected = role_spent + estimated_tokens
        if projected > role_limit:
            raise BudgetExceededError(role, role_spent, role_limit,
                                      self.total_spent, self.ceiling.max_total_tokens)

        total_projected = self.total_spent + estimated_tokens
        if total_projected > self.ceiling.max_total_tokens:
            raise BudgetExceededError(
                role, role_spent, role_limit,
                self.total_spent, self.ceiling.max_total_tokens,
            )

    def record(self, role: str, tokens: int) -> None:
        self.spent_per_role[role] = self.spent_per_role.get(role, 0) + tokens
        self.total_spent += tokens
        logger.debug("%s: +%d tokens (累计: %d)", role, tokens,
                     self.spent_per_role[role])

    def check_and_record(self, role: str, estimated: int,
                         actual: int) -> None:
        self.record(role, actual)

    def summary(self) -> str:
        lines = ["--- 预算使用状态 ---"]
        total = 0
        for role, spent in sorted(self.spent_per_role.items(),
                                   key=lambda x: -x[1]):
            limit = self.ceiling.max_tokens_per_role.get(role, 20000)
            pct = spent / limit * 100 if limit else 0
            lines.append(f"  {role:16s} {spent:>8,}/{limit:>8,} ({pct:.0f}%)")
            total += spent
        total_pct = total / self.ceiling.max_total_tokens * 100 if self.ceiling.max_total_tokens else 0
        lines.append(f"  {'总计':16s} {total:>8,}/{self.ceiling.max_total_tokens:>8,} ({total_pct:.0f}%)")
        return "\n".join(lines)
