from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from src.config import TeamConfig
from src.llm import LLMClient, LLMResponse, StubLLMClient, LLMFactory


@dataclass
class MergedDiff:
    patch: str
    files_changed: list[str]
    conflict_files: list[str] = field(default_factory=list)
    conflicts_resolved: int = 0
    conflicts_failed: int = 0


MERGE_SYSTEM = """你是一个代码合并专家。你收到两个或多个分支对同一个文件的不同修改。
请生成一个合并后的完整文件内容，保留所有分支的正确逻辑。

规则：
1. 当修改不重叠时，保留所有修改
2. 当修改冲突时，选择语义上更合理的版本
3. 如果两个修改都正确但互斥，保留更完整的版本，并在注释中标注替代方案
4. 只输出合并后的文件内容，不要输出解释

输出格式：
```
<<<FILE: path/to/file.py>>>
[合并后的完整文件内容]
<<<END>>>
```"""


class MergeCoordinator:
    def __init__(self, config: TeamConfig, client: LLMClient | None = None):
        self.config = config
        spec = config.role_models["merge_coord"]
        self.client = client or LLMFactory.get(spec)
        self.model = spec.model_id

    def run(self, diffs: list, repo_path: str, base_branch: str = "main",
            staging_branch: str = "agent/staging") -> MergedDiff:
        self._checkout_base(repo_path, base_branch)
        subprocess.run(
            ["git", "-C", repo_path, "checkout", "-B", staging_branch, base_branch],
            capture_output=True, timeout=10,
        )

        all_files: set[str] = set()
        merge_failures: list[str] = []

        for diff in diffs:
            source_branch = getattr(diff, 'branch', None)
            if source_branch is None and hasattr(diff, 'subtask_name'):
                source_branch = f"agent/coder/{diff.subtask_name}"
            if source_branch is None:
                source_branch = f"agent/{diff.subtask_name}"
            try:
                result = subprocess.run(
                    ["git", "-C", repo_path, "merge", source_branch,
                     "--no-commit", "--no-ff"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode != 0:
                    merge_failures.append(source_branch)
            except subprocess.TimeoutExpired:
                merge_failures.append(source_branch)
            for f in getattr(diff, 'files_changed', []):
                all_files.add(f)

        conflicts: list[str] = []
        if merge_failures:
            status = subprocess.run(
                ["git", "-C", repo_path, "diff", "--name-only", "--diff-filter=U"],
                capture_output=True, text=True, timeout=10,
            )
            conflicts = [f.strip() for f in status.stdout.split("\n") if f.strip()]

        resolved = 0
        failed = 0
        for cf in conflicts:
            ok = self._resolve_conflict(repo_path, cf)
            if ok:
                resolved += 1
            else:
                failed += 1

        if not merge_failures or resolved == len(conflicts):
            subprocess.run(
                ["git", "-C", repo_path, "commit", "-m",
                 f"[agent] merge {len(diffs)} branches"],
                capture_output=True, timeout=10,
            )
        else:
            subprocess.run(["git", "-C", repo_path, "merge", "--abort"],
                           capture_output=True, timeout=10)

        patch_result = subprocess.run(
            ["git", "-C", repo_path, "diff", f"{base_branch}..{staging_branch}"],
            capture_output=True, text=True, timeout=10,
        )
        return MergedDiff(
            patch=patch_result.stdout,
            files_changed=sorted(all_files),
            conflict_files=conflicts,
            conflicts_resolved=resolved,
            conflicts_failed=failed,
        )

    def _resolve_conflict(self, repo_path: str, filepath: str) -> bool:
        full = f"{repo_path}/{filepath}"
        try:
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError):
            return False

        response = self.client.chat(
            system=MERGE_SYSTEM,
            user=f"解决以下文件中的 Git 合并冲突：\n\n=== {filepath} ===\n{content}",
            model=self.model, max_tokens=4096,
        )

        merged = self._parse_merge_response(response.content)
        if merged:
            with open(full, "w", encoding="utf-8") as f:
                f.write(merged + "\n")
            subprocess.run(["git", "-C", repo_path, "add", filepath],
                           capture_output=True, timeout=5)
            return True
        return False

    def _parse_merge_response(self, content: str) -> str | None:
        if "<<<FILE:" in content and "<<<END>>>" in content:
            start = content.index("<<<FILE:") + 7
            start = content.index("\n", start) + 1
            end = content.index("<<<END>>>")
            return content[start:end].strip()
        return content.strip() if content.strip() else None

    @staticmethod
    def _checkout_base(repo_path: str, base_branch: str) -> None:
        try:
            result = subprocess.run(
                ["git", "-C", repo_path, "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            current = result.stdout.strip()
            if current == base_branch:
                return
            subprocess.run(
                ["git", "-C", repo_path, "checkout", base_branch],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass
