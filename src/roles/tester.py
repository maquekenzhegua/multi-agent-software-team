from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass, field

from src.config import TeamConfig
from src.llm import LLMClient, LLMResponse, StubLLMClient, LLMFactory


@dataclass
class TestResult:
    passed: bool
    total: int = 0
    passed_count: int = 0
    failed_count: int = 0
    error_count: int = 0
    failure_log: str = ""
    tokens_used: int = 0


TESTER_SYSTEM = """你是一位质量保障工程师。你运行测试套件并分析失败原因。

当测试失败时，你需要：
1. 阅读失败日志和堆栈跟踪
2. 确定是哪个子任务引入了失败
3. 给出具体的修复建议

输出格式：
如果全部通过：
  PASSED: <N>/<N> 测试通过

如果有失败：
  FAILED: <N> failed, <M> errors
  目标子任务: <名称>
  原因: <简要分析>
  建议: <修复建议>"""


class Tester:
    def __init__(self, config: TeamConfig, client: LLMClient | None = None):
        self.config = config
        spec = config.role_models["tester"]
        self.client = client or LLMFactory.get(spec)
        self.model = spec.model_id

    def run(self, repo_path: str, test_command: str = "pytest",
            sandbox_image: str = "") -> TestResult:
        if sandbox_image and self.config.execute_tests:
            return self._run_in_sandbox(repo_path, test_command, sandbox_image)
        return self._run_local(repo_path, test_command)

    def _run_local(self, repo_path: str, test_command: str) -> TestResult:
        parts = test_command.split()
        try:
            result = subprocess.run(
                parts, cwd=repo_path, capture_output=True, text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=False, failure_log="测试超时（超过 120 秒）",
            )
        except FileNotFoundError:
            return self._analyze_with_llm(
                repo_path, "", "无可执行测试（未找到测试框架）")

        stdout = result.stdout
        stderr = result.stderr
        full_output = f"{stdout}\n{stderr}".strip()

        if result.returncode == 0:
            total, passed_count = self._parse_test_counts(full_output)
            return TestResult(
                passed=True, total=total, passed_count=passed_count,
            )

        total, passed_count, failed, errors = self._parse_test_counts_detailed(full_output)
        analysis = self._analyze_with_llm(repo_path, full_output, "")

        return TestResult(
            passed=False, total=total, passed_count=passed_count,
            failed_count=failed, error_count=errors,
            failure_log=full_output[:3000],
            tokens_used=analysis.total_tokens if hasattr(analysis, 'total_tokens') else 0,
        )

    def _run_in_sandbox(self, repo_path: str, test_command: str,
                        image: str) -> TestResult:
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{repo_path}:/workspace",
            "-w", "/workspace",
            image,
            "bash", "-c", test_command,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            return TestResult(passed=False, failure_log="沙箱测试超时")
        except FileNotFoundError:
            return TestResult(passed=False, failure_log="Docker 未安装或不可用")

        output = f"{result.stdout}\n{result.stderr}".strip()
        if result.returncode == 0:
            total, passed_count = self._parse_test_counts(output)
            return TestResult(passed=True, total=total, passed_count=passed_count)
        total, passed_count, failed, errors = self._parse_test_counts_detailed(output)
        return TestResult(
            passed=False, total=total, passed_count=passed_count,
            failed_count=failed, error_count=errors, failure_log=output[:3000],
        )

    def _analyze_with_llm(self, repo_path: str, test_output: str,
                          extra: str) -> LLMResponse:
        return self.client.chat(
            system=TESTER_SYSTEM,
            user=f"测试输出:\n{test_output or extra}",
            model=self.model,
            max_tokens=2048,
        )

    def _parse_test_counts(self, output: str) -> tuple[int, int]:
        import re
        match = re.search(r"(\d+)\s+passed", output)
        if match:
            passed = int(match.group(1))
            total_match = re.search(r"(\d+)\s+total", output)
            total = int(total_match.group(1)) if total_match else passed
            return total, passed
        return 0, 0

    def _parse_test_counts_detailed(self, output: str
                                    ) -> tuple[int, int, int, int]:
        import re
        total = 0
        passed = 0
        failed = 0
        errors = 0
        m = re.search(r"(\d+)\s+passed", output)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", output)
        if m:
            failed = int(m.group(1))
        m = re.search(r"(\d+)\s+errors?", output)
        if m:
            errors = int(m.group(1))
        total = passed + failed + errors
        return total or 0, passed, failed, errors


class StubTester(Tester):
    """测试用 stub，不执行真实测试命令"""

    def __init__(self, config: TeamConfig | None = None):
        canned = {"default": "PASSED: 42/42 测试通过"}
        super().__init__(config or TeamConfig(), StubLLMClient(canned))

    def run(self, repo_path: str, test_command: str = "pytest",
            sandbox_image: str = "") -> TestResult:
        return TestResult(passed=True, total=42, passed_count=42)


def create_stub_tester() -> Tester:
    return StubTester()
