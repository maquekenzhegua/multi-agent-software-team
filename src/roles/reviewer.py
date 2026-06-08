from __future__ import annotations

from dataclasses import dataclass, field

from src.config import TeamConfig
from src.llm import LLMClient, LLMResponse, StubLLMClient, LLMFactory


@dataclass
class ReviewResult:
    approved: bool
    comments: list[str] = field(default_factory=list)
    target_coder: str = ""
    tokens_used: int = 0
    false_approve: bool = False


REVIEWER_SYSTEM = """你是一位严格的代码审查者。你的职责是审查代码变更，找出 Bug、逻辑错误、安全隐患和风格问题。

审查规则：
1. 查找可能导致运行时错误的代码（None 解引用、未处理的异常、类型不匹配）
2. 查找逻辑错误（条件反了、边界条件遗漏、死循环）
3. 查找安全问题（注入、权限绕过、密钥泄露）
4. 检查代码是否满足 PR 描述和子任务规范
5. 你绝对不能批准自己写的代码

输出格式：
如果通过：
  APPROVED

如果需要修改：
  FEEDBACK:<子任务名称>
  - 文件: <路径>, 行: <行号或区域>, 问题: <具体描述>, 建议: <修改建议>
  - ...

如果发现严重问题需要重新规划：
  REPLAN_NEEDED: <原因>"""


class Reviewer:
    def __init__(self, config: TeamConfig, client: LLMClient | None = None):
        self.config = config
        spec = config.role_models["reviewer"]
        self.client = client or LLMFactory.get(spec)
        self.model = spec.model_id
        self._reviewed_diff_hashes: set[str] = set()

    def run(self, patch: str, subtask_names: list[str],
            authors: list[str],
            inject_known_bug: bool = False) -> ReviewResult:
        if any(a in self._reviewed_diff_hashes for a in authors):
            return ReviewResult(
                approved=False,
                comments=["硬约束：审查者不能审查自己或同角色人员创作的代码"],
                tokens_used=0,
            )

        prompt = self._build_prompt(patch, subtask_names)
        response = self.client.chat(
            system=REVIEWER_SYSTEM, user=prompt, model=self.model,
            max_tokens=4096,
        )

        result = self._parse_review(response.content)
        result.tokens_used = response.total_tokens

        if inject_known_bug and result.approved:
            result.false_approve = True
            result.comments.append("[探测] 审查者未发现已注入的已知 Bug — 误批")

        self._reviewed_diff_hashes.update(authors)
        return result

    def _build_prompt(self, patch: str, subtask_names: list[str]) -> str:
        return (
            f"审查以下 {len(subtask_names)} 个子任务合并后的 diff：\n"
            f"涉及子任务: {', '.join(subtask_names)}\n\n"
            f"```diff\n{patch[:12000]}\n```"
        )

    def _parse_review(self, content: str) -> ReviewResult:
        content = content.strip()
        if content.startswith("APPROVED"):
            return ReviewResult(approved=True, comments=[content])
        if content.startswith("REPLAN_NEEDED"):
            reason = content.split(":", 1)[1].strip() if ":" in content else content
            return ReviewResult(approved=False,
                               comments=[f"需要重新规划: {reason}"])
        lines = content.split("\n")
        comments: list[str] = []
        target = ""
        in_feedback = False
        for line in lines:
            if line.startswith("FEEDBACK:"):
                target = line.split(":", 1)[1].strip()
                in_feedback = True
            elif in_feedback and line.strip().startswith("-"):
                comments.append(line.strip())
        if not comments:
            comments.append(content)
        return ReviewResult(
            approved=False, comments=comments, target_coder=target,
        )


def _analyze_stub_review(patch: str, subtask_names: list[str],
                         inject_known_bug: bool) -> ReviewResult:
    if inject_known_bug:
        obvious_bugs = ["return None", "pass", "raise SystemExit", "1/0"]
        has_obvious = any(b in patch for b in obvious_bugs)
        off_by_one = "range(len(items) - 1)" in patch
        if has_obvious:
            return ReviewResult(
                approved=False,
                comments=[f"- 文件: src/main.py, 问题: 发现注入 Bug",
                          f"- 建议: 修复代码逻辑"],
                target_coder="coder-A",
            )
        if off_by_one:
            return ReviewResult(
                approved=True, comments=["APPROVED"],
                false_approve=True,
            )
        return ReviewResult(
            approved=True, comments=["APPROVED"],
            false_approve=True,
        )

    lower = patch.lower()
    issues = []
    if "TODO" in patch or "FIXME" in patch:
        issues.append("- 文件: 多处, 问题: 存在未完成的 TODO/FIXME 标记")
    if "print(" in patch and "logger" not in lower:
        issues.append("- 文件: 多处, 问题: 使用 print() 而非结构化日志")
    if "except:" in patch or "except Exception:" in patch:
        issues.append("- 文件: 多处, 问题: 裸 except 可能掩盖错误")

    if issues:
        return ReviewResult(
            approved=False,
            comments=issues,
            target_coder=f"coder-{subtask_names[0][0].upper() if subtask_names else 'A'}",
        )
    return ReviewResult(approved=True, comments=["APPROVED"])


class DynamicStubReviewer(Reviewer):
    def run(self, patch: str, subtask_names: list[str],
            authors: list[str],
            inject_known_bug: bool = False) -> ReviewResult:
        if any(a in self._reviewed_diff_hashes for a in authors):
            return ReviewResult(
                approved=False,
                comments=["硬约束：审查者不能审查自己或同角色人员创作的代码"],
                tokens_used=0,
            )
        result = _analyze_stub_review(patch, subtask_names, inject_known_bug)
        self._reviewed_diff_hashes.update(authors)
        return result


def create_stub_reviewer() -> Reviewer:
    config = TeamConfig()
    return DynamicStubReviewer(config, StubLLMClient({"default": "APPROVED"}))
