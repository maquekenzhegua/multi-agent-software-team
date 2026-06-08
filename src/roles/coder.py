from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass, field
from fnmatch import fnmatch

from src.config import TeamConfig
from src.llm import LLMClient, LLMResponse, StubLLMClient, LLMFactory
from src.roles.architect import Subtask


CODER_SYSTEM = """你是一位资深软件工程师，正在为一个现有代码库贡献代码。

你会收到：
1. 一个子任务规范（需要做什么）
2. 现有代码库的结构概览（目录树、依赖关系）
3. 需要修改的文件的当前内容

你的任务是在指定文件中实现该子任务。

规则：
1. 只修改分配给此子任务的文件 — 不要碰其他文件
2. 保持与现有代码库风格完全一致（命名、缩进、导入风格）
3. 实现必须完整：包含所有必要的 import、类型标注、文档字符串和错误处理
4. 如果子任务提到"添加测试"，编写实际有用的测试用例
5. 不要输出解释性文字，只输出代码

输出格式（严格遵守）：
```<文件路径>
<文件完整内容>
```
多个文件用空行分隔。"""


def scan_repo(repo_path: str, ignore_patterns: list[str] | None = None
              ) -> dict[str, str]:
    """扫描仓库结构，返回 {文件路径: 文件内容} 的字典。

    最多读取 50 个文件，每个文件最多 3000 字符。自动跳过二进制文件。"""
    ignore = ignore_patterns or ["__pycache__", "*.pyc", ".git", ".team",
                                  "node_modules", ".venv", "venv", "*.egg-info"]
    result: dict[str, str] = {}
    file_count = 0

    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if not any(fnmatch(d, p) for p in ignore)]

        for fname in sorted(files):
            if any(fnmatch(fname, p) for p in ignore):
                continue
            if file_count >= 50:
                return result
            fpath = os.path.join(root, fname)
            rel = os.path.relpath(fpath, repo_path)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    content = f.read(3000)
                if "\0" not in content:
                    result[rel] = content
                    file_count += 1
            except (UnicodeDecodeError, OSError):
                continue

    return result


def build_context_prompt(subtask, existing_files: dict[str, str],
                         repo_structure: dict[str, str]) -> str:
    """构建完整的上下文提示。"""
    parts = [f"## 子任务\n名称: {subtask.name}\n描述: {subtask.description}"]
    if subtask.interfaces:
        parts.append(f"接口要求: {', '.join(subtask.interfaces)}")
    if subtask.dependencies:
        parts.append(f"依赖子任务: {', '.join(subtask.dependencies)}")

    py_files = {p: c for p, c in repo_structure.items() if p.endswith(".py")}
    if py_files:
        parts.append("\n## 仓库结构\n```")
        for p in sorted(py_files):
            parts.append(f"  {p}  ({len(py_files[p])} 字符)")
        parts.append("```")

    if existing_files:
        parts.append("\n## 需要修改的文件（当前内容）")
        for fpath, content in existing_files.items():
            parts.append(f"\n### {fpath}\n```python\n{content}\n```")

    parts.append("\n请实现上述子任务，输出每个修改文件的完整内容。")
    return "\n".join(parts)


@dataclass
class DiffResult:
    subtask_name: str
    files_changed: list[str]
    patch: str
    lines_added: int
    lines_removed: int
    tokens_used: int


class Coder:
    def __init__(self, name: str, config: TeamConfig,
                 client: LLMClient | None = None):
        self.name = name
        self.config = config
        spec = config.role_models["coder"]
        self.client = client or LLMFactory.get(spec)
        self.model = spec.model_id
        self.max_tokens = config.budget.max_tokens_per_role.get("coder", 15000)

    def run(self, subtask: Subtask, repo_path: str,
            worktree_base: str) -> DiffResult:
        worktree_path = os.path.join(worktree_base, f"wt-{self.name}-{subtask.name}")
        branch = f"agent/{self.name}/{subtask.name}"

        self._create_worktree(repo_path, worktree_path, branch)

        repo_structure = scan_repo(worktree_path)

        file_contents = {}
        for fpath in subtask.files:
            full = os.path.join(worktree_path, fpath)
            if os.path.exists(full):
                try:
                    file_contents[fpath] = open(full, "r", encoding="utf-8").read()
                except (UnicodeDecodeError, OSError):
                    pass

        prompt = build_context_prompt(subtask, file_contents, repo_structure)
        response = self.client.chat(
            system=CODER_SYSTEM, user=prompt, model=self.model,
            max_tokens=self.max_tokens,
        )

        files_written = self._apply_output(response.content, worktree_path,
                                            subtask.files)
        patch, added, removed = self._commit_and_diff(worktree_path, branch)

        return DiffResult(
            subtask_name=subtask.name,
            files_changed=files_written or subtask.files,
            patch=patch,
            lines_added=added,
            lines_removed=removed,
            tokens_used=response.total_tokens,
        )

    def _apply_output(self, content: str, worktree_path: str,
                      target_files: list[str]) -> list[str]:
        """解析 LLM 输出并写入文件。

        支持三种格式：
        1. ```path/to/file.py\\n...\\n```  (最常见)
        2. <<<FILE: path/to/file.py>>>\\n...\\n<<<END>>>
        3. ### path/to/file.py\\n```python\\n...\\n```
        """
        written: list[str] = []

        blocks = self._parse_markdown_blocks(content)
        if blocks:
            for fname, code in blocks.items():
                full_path = os.path.join(worktree_path, fname)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(code + "\n")
                written.append(fname)
            return written

        blocks = self._parse_file_tags(content)
        if blocks:
            for fname, code in blocks.items():
                full_path = os.path.join(worktree_path, fname)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(code + "\n")
                written.append(fname)
            return written

        if target_files and len(target_files) == 1:
            full_path = os.path.join(worktree_path, target_files[0])
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            code = self._extract_code_block(content)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(code + "\n")
            written.append(target_files[0])

        return written

    @staticmethod
    def _parse_markdown_blocks(content: str) -> dict[str, str]:
        """解析 ```<path>\\n...\\n``` 格式。"""
        import re
        result: dict[str, str] = {}
        pattern = r"```(?:python|py|typescript|ts|rust|rs|julia|jl)?\s*\n([^\n].*?)\n(.*?)```"
        matches = list(re.finditer(pattern, content, re.DOTALL))
        if not matches:
            pattern2 = r"```\s*(\S+\.(?:py|ts|rs|jl|js|txt|toml|yml|yaml|json|md))\s*\n(.*?)```"
            matches = list(re.finditer(pattern2, content, re.DOTALL))
        for m in matches:
            if len(m.groups()) >= 2:
                header_or_code = m.group(1).strip()
                code = m.group(2).strip()
                if "." in header_or_code and "/" not in header_or_code and len(header_or_code) < 80:
                    fname = header_or_code
                elif len(m.groups()) >= 2:
                    fname = f"unknown_{len(result)}.py"
                result[fname] = code
        return result

    @staticmethod
    def _parse_file_tags(content: str) -> dict[str, str]:
        """解析 <<<FILE: path>>> ... <<<END>>> 格式。"""
        result: dict[str, str] = {}
        blocks = content.split("<<<FILE:")
        for block in blocks:
            if not block.strip() or "<<<END>>>" not in block:
                continue
            header_end = block.index("\n") if "\n" in block else 0
            fname = block[:header_end].strip().rstrip(">").strip()
            code_start = block.index("\n", header_end) + 1 if "\n" in block[header_end:] else 0
            code_end = block.index("<<<END>>>")
            code = block[code_start:code_end].strip()
            if fname and code:
                result[fname] = code
        return result

    @staticmethod
    def _extract_code_block(content: str) -> str:
        """从文本中提取代码块，去除标记。"""
        code = content.strip()
        if code.startswith("```"):
            lines = code.split("\n")
            if len(lines) > 1:
                code = "\n".join(lines[1:])
            if code.endswith("```"):
                code = code[:-3].strip()
        return code

    def _build_prompt(self, subtask: Subtask,
                      existing: dict[str, str]) -> str:
        parts = [f"子任务: {subtask.name}"]
        parts.append(f"描述: {subtask.description}")
        if subtask.interfaces:
            parts.append(f"接口: {', '.join(subtask.interfaces)}")
        if subtask.dependencies:
            parts.append(f"依赖: {', '.join(subtask.dependencies)}")
        parts.append(f"需修改的文件: {', '.join(subtask.files)}")
        if existing:
            parts.append("\n--- 现有文件内容 ---")
            for fpath, content in existing.items():
                parts.append(f"\n=== {fpath} ===\n{content}")
        parts.append("\n请实现上述子任务，输出每个修改文件的完整内容。")
        return "\n".join(parts)

    def _apply_code(self, content: str, worktree_path: str) -> list[str]:
        written: list[str] = []
        blocks = content.split("<<<FILE:")
        for block in blocks:
            if not block.strip():
                continue
            if "<<<END>>>" not in block:
                continue
            header_end = block.index("\n") if "\n" in block else 0
            fpath = block[:header_end].strip().rstrip(">").strip()
            code_start = block.index("\n", header_end) + 1 if "\n" in block[header_end:] else 0
            code_end = block.index("<<<END>>>")
            code = block[code_start:code_end].strip()

            full_path = os.path.join(worktree_path, fpath)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(code + "\n")
            written.append(fpath)
        return written

    def _commit_and_diff(self, worktree_path: str, branch: str
                         ) -> tuple[str, int, int]:
        subprocess.run(["git", "-C", worktree_path, "add", "-A"],
                       capture_output=True, timeout=10)
        subprocess.run(["git", "-C", worktree_path, "commit", "-m",
                        f"[agent] implement {branch}"],
                       capture_output=True, timeout=10)
        diff_result = subprocess.run(
            ["git", "-C", worktree_path, "diff", "HEAD~1..HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        patch = diff_result.stdout
        added = patch.count("\n+") - patch.count("\n+++")
        removed = patch.count("\n-") - patch.count("\n---")
        return patch, max(added, 0), max(removed, 0)

    @staticmethod
    def _create_worktree(repo_path: str, worktree_path: str, branch: str) -> None:
        os.makedirs(worktree_path, exist_ok=True)
        subprocess.run(["git", "-C", repo_path, "worktree", "add", "-b", branch,
                        worktree_path], capture_output=True, timeout=15)


def _generate_stub_code(subtask_name: str, description: str,
                        files: list[str]) -> str:
    blocks = []
    for fpath in files:
        if "test" in fpath.lower():
            code = _test_file_content(subtask_name)
        elif "lock" in fpath.lower():
            code = _lock_file_content()
        elif "cache" in fpath.lower():
            code = _cache_file_content()
        elif "api" in fpath.lower() or "route" in fpath.lower():
            code = _api_file_content(fpath)
        elif "model" in fpath.lower():
            code = _model_file_content(fpath)
        elif "validate" in fpath.lower():
            code = _validate_file_content()
        elif "parser" in fpath.lower():
            code = _parser_file_content()
        elif "middleware" in fpath.lower():
            code = _middleware_file_content()
        elif "error" in fpath.lower() or "logger" in fpath.lower():
            code = _error_file_content(fpath)
        elif "handler" in fpath.lower():
            code = _handler_file_content()
        elif "migrate" in fpath.lower():
            code = _migration_file_content()
        elif "core" in fpath.lower():
            code = _core_file_content()
        else:
            code = _generic_file_content(fpath, subtask_name, description)
        blocks.append(f"<<<FILE: {fpath}>>>\n{code}\n<<<END>>>")
    return "\n".join(blocks)


def _test_file_content(name: str) -> str:
    return f'''"""Tests for {name}"""


def test_{name}_basic():
    assert True


def test_{name}_edge_case():
    assert 1 + 1 == 2


def test_{name}_integration():
    result = {{"status": "ok"}}
    assert result["status"] == "ok"
'''


def _lock_file_content() -> str:
    return '''import threading
from contextlib import contextmanager


class RWLock:
    def __init__(self):
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self):
        with self._lock:
            yield

    def release(self):
        pass
'''


def _cache_file_content() -> str:
    return '''import threading
from typing import Any


class Cache:
    def __init__(self, max_size: int = 1024):
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key: str) -> Any | None:
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            if len(self._data) >= self._max_size:
                oldest = next(iter(self._data))
                del self._data[oldest]
            self._data[key] = value
'''


def _api_file_content(fpath: str) -> str:
    return '''from typing import Any


def handle_request(req: dict[str, Any]) -> dict[str, Any]:
    method = req.get("method", "GET")
    path = req.get("path", "/")
    body = req.get("body", {})

    handlers = {
        "GET": lambda p, b: {"status": "ok", "data": None},
        "POST": lambda p, b: {"status": "created", "data": b},
        "DELETE": lambda p, b: {"status": "deleted"},
    }

    handler = handlers.get(method, lambda p, b: {"status": "error", "message": "method not allowed"})
    return handler(path, body)
'''


def _model_file_content(fpath: str) -> str:
    return '''from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Entity:
    id: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Entity":
        return cls(id=d.get("id", ""), data=d.get("data", {}))
'''


def _validate_file_content() -> str:
    return '''from typing import Any


def validate_input(data: Any) -> bool:
    if data is None:
        return False
    if isinstance(data, str) and len(data.strip()) == 0:
        return False
    if isinstance(data, (int, float)) and data < 0:
        return False
    return True


def validate_config(config: dict) -> list[str]:
    errors = []
    required = ["name", "version"]
    for key in required:
        if key not in config:
            errors.append(f"missing required field: {key}")
    return errors
'''


def _parser_file_content() -> str:
    return '''from typing import Any


class AST:
    def __init__(self, kind: str, value: Any, children: list["AST"] | None = None):
        self.kind = kind
        self.value = value
        self.children = children or []


def parse(input_str: str) -> AST:
    tokens = input_str.strip().split()
    if not tokens:
        return AST("empty", None)
    root = AST("root", None)
    for token in tokens:
        root.children.append(AST("token", token))
    return root
'''


def _middleware_file_content() -> str:
    return '''from typing import Any, Callable


Handler = Callable[[dict[str, Any]], dict[str, Any]]


def auth_middleware(handler: Handler) -> Handler:
    def wrapper(req: dict[str, Any]) -> dict[str, Any]:
        token = req.get("headers", {}).get("Authorization", "")
        if not token.startswith("Bearer "):
            return {"status": "error", "message": "unauthorized"}
        return handler(req)
    return wrapper


def rate_limit_middleware(handler: Handler, max_req: int = 100) -> Handler:
    count = 0

    def wrapper(req: dict[str, Any]) -> dict[str, Any]:
        nonlocal count
        if count >= max_req:
            return {"status": "error", "message": "rate limit exceeded"}
        count += 1
        return handler(req)
    return wrapper
'''


def _error_file_content(fpath: str) -> str:
    return '''import logging

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


def log_error(error: Exception) -> None:
    logger.error("error occurred: %s", error, exc_info=True)
'''


def _handler_file_content() -> str:
    return '''from typing import Any


def create_resource(data: dict[str, Any]) -> dict[str, Any]:
    if not data:
        return {"status": "error", "message": "empty data"}
    return {"status": "created", "id": "res-001", "data": data}


def get_resource(resource_id: str) -> dict[str, Any]:
    return {"status": "ok", "id": resource_id, "data": {"name": "sample"}}


def list_resources() -> dict[str, Any]:
    return {"status": "ok", "items": []}


def delete_resource(resource_id: str) -> dict[str, Any]:
    return {"status": "deleted", "id": resource_id}
'''


def _migration_file_content() -> str:
    return '''from typing import Any


MIGRATIONS: list[dict[str, Any]] = []


def migrate() -> None:
    for mig in MIGRATIONS:
        _apply(mig)


def _apply(migration: dict[str, Any]) -> None:
    name = migration.get("name", "unknown")
    print(f"applying migration: {name}")
'''


def _core_file_content() -> str:
    return '''from typing import Any


class Engine:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    def configure(self, **kwargs: Any) -> None:
        self.config.update(kwargs)

    def run(self, input_data: Any) -> dict[str, Any]:
        if not self.config:
            self.configure(default_mode=True)
        return {"status": "ok", "result": input_data, "config": self.config}
'''


def _generic_file_content(fpath: str, name: str, description: str) -> str:
    return f'''"""Implemented for task: {name}

{description}
"""

from typing import Any


def main() -> dict[str, Any]:
    return {{"status": "ok", "task": "{name}"}}
'''


class DynamicStubCoder(Coder):
    def __init__(self, name: str, config: TeamConfig | None = None):
        canned = {"default": "dynamic"}
        super().__init__(name, config or TeamConfig(), StubLLMClient(canned))

    def run(self, subtask, repo_path: str, worktree_base: str):
        files = list(subtask.files)
        if files == ["*"] or files == ["*"]:
            files = [f"src/{subtask.name}.py"]

        code = _generate_stub_code(subtask.name, subtask.description, files)
        files_written = self._apply_output(code, repo_path, files)
        patch = f"stub-diff-for-{subtask.name}"
        lines = code.count("\n")
        return DiffResult(
            subtask_name=subtask.name,
            files_changed=files_written or files,
            patch=patch,
            lines_added=lines,
            lines_removed=0,
            tokens_used=len(code) // 4 + len(subtask.description) // 4,
        )


def create_stub_coder(name: str, canned_outputs: dict[str, str] | None = None
                      ) -> Coder:
    return DynamicStubCoder(name)
