from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field

from src.config import TeamConfig, ModelProvider
from src.llm import LLMClient, LLMResponse, StubLLMClient, LLMFactory


@dataclass
class Subtask:
    name: str
    description: str
    files: list[str]
    interfaces: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    assigned_to: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "files": self.files,
            "interfaces": self.interfaces,
            "dependencies": self.dependencies,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Subtask:
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            files=d.get("files", []),
            interfaces=d.get("interfaces", []),
            dependencies=d.get("dependencies", []),
        )


ARCHITECT_SYSTEM = """你是一位高级软件架构师。你的职责是分析 GitHub Issue 并生成一个结构化的实现计划。

对于给定的 Issue，你需要：
1. 理解需求并写出一句话摘要
2. 将工作拆分为 3-8 个独立的子任务
3. 每个子任务必须明确：涉及哪些文件、公共接口是什么、依赖哪些其他子任务

输出格式必须是 JSON，结构如下：
{
  "summary": "一句话描述",
  "subtasks": [
    {
      "name": "子任务简称",
      "description": "这个子任务做什么",
      "files": ["src/file1.py", "src/file2.py"],
      "interfaces": ["function_a(param1, param2) -> ReturnType"],
      "dependencies": ["子任务名称"]
    }
  ]
}

确保子任务之间的依赖关系构成一个 DAG（无环）。子任务之间文件集应尽量不重叠。"""


class Architect:
    def __init__(self, config: TeamConfig, client: LLMClient | None = None):
        self.config = config
        spec = config.role_models["architect"]
        self.client = client or LLMFactory.get(spec)
        self.model = spec.model_id

    def run(self, issue_text: str) -> tuple[str, list[Subtask], LLMResponse]:
        response = self.client.chat(
            system=ARCHITECT_SYSTEM,
            user=f"分析以下 GitHub Issue，生成实现计划：\n\n{issue_text}",
            model=self.model,
            max_tokens=4096,
        )
        plan_data = self._parse_response(response.content)
        summary = plan_data.get("summary", "无法解析计划摘要")
        subtasks = [Subtask.from_dict(s) for s in plan_data.get("subtasks", [])]
        return summary, subtasks, response

    def _parse_response(self, content: str) -> dict:
        content = content.strip()
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            content = content[start:end]
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            content = content[start:end]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return self._regex_parse(content)

    def _regex_parse(self, content: str) -> dict:
        import re
        subtasks: list[dict] = []
        summary = ""
        for line in content.split("\n"):
            if "summary" in line.lower() and ":" in line:
                summary = line.split(":", 1)[1].strip().strip('"').strip("'")
        name_matches = re.findall(r'"name"\s*:\s*"([^"]+)"', content)
        desc_matches = re.findall(r'"description"\s*:\s*"([^"]+)"', content)
        files_matches = re.findall(r'"files"\s*:\s*\[([^\]]*)\]', content)
        for i, name in enumerate(name_matches):
            sub = {"name": name, "description": desc_matches[i] if i < len(desc_matches) else "",
                   "files": [], "interfaces": [], "dependencies": []}
            if i < len(files_matches):
                sub["files"] = [f.strip().strip('"').strip("'") for f in files_matches[i].split(",") if f.strip()]
            subtasks.append(sub)
        return {"summary": summary, "subtasks": subtasks}

    @staticmethod
    def fetch_issue(issue_url: str) -> str:
        result = subprocess.run(
            ["gh", "issue", "view", issue_url, "--json", "title,body,labels"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return f"Issue URL: {issue_url}\n(无法通过 gh CLI 获取，请确认已安装 GitHub CLI 并登录)"
        data = json.loads(result.stdout)
        title = data.get("title", "")
        body = data.get("body", "")
        labels = [l["name"] for l in data.get("labels", [])]
        return f"标题: {title}\n标签: {', '.join(labels)}\n\n内容:\n{body}"


def _generate_stub_plan(issue_text: str) -> dict:
    text_lower = issue_text.lower()

    if "race" in text_lower or "竞态" in text_lower or "并发" in text_lower:
        return {
            "summary": "修复竞态条件：为共享状态添加线程安全保护",
            "subtasks": [
                {"name": "lock", "description": "添加线程锁机制",
                 "files": ["src/lock.py"], "interfaces": ["acquire()", "release()"], "dependencies": []},
                {"name": "parser", "description": "修复解析器中的竞态条件",
                 "files": ["src/parser.py"], "interfaces": ["parse(s: str) -> AST"], "dependencies": ["lock"]},
                {"name": "cache", "description": "缓存层加锁保护",
                 "files": ["src/cache.py"], "interfaces": ["Cache.get(k)", "Cache.set(k,v)"], "dependencies": ["lock"]},
                {"name": "test", "description": "并发压力测试",
                 "files": ["tests/test_concurrent.py"], "interfaces": ["test_race_condition()"], "dependencies": ["parser", "cache"]},
            ]
        }
    if "refactor" in text_lower or "重构" in text_lower:
        return {
            "summary": "重构代码架构，提取公共模块并简化接口",
            "subtasks": [
                {"name": "extract_core", "description": "提取核心抽象为独立模块",
                 "files": ["src/core.py"], "interfaces": ["Engine.run()", "Engine.configure()"], "dependencies": []},
                {"name": "simplify_api", "description": "简化对外 API 层",
                 "files": ["src/api.py"], "interfaces": ["handle(req) -> Response"], "dependencies": ["extract_core"]},
                {"name": "cleanup", "description": "移除废弃代码和旧接口",
                 "files": ["src/legacy.py", "src/deprecated.py"], "interfaces": [], "dependencies": ["simplify_api"]},
                {"name": "update_tests", "description": "更新测试以匹配新架构",
                 "files": ["tests/test_core.py", "tests/test_api.py"], "interfaces": [], "dependencies": ["extract_core"]},
            ]
        }
    if "bug" in text_lower or "fix" in text_lower or "修复" in text_lower:
        return {
            "summary": "修复 Bug：处理边界条件并加强输入验证",
            "subtasks": [
                {"name": "validate", "description": "添加输入验证层",
                 "files": ["src/validate.py"], "interfaces": ["validate_input(d) -> bool"], "dependencies": []},
                {"name": "fix_logic", "description": "修正核心逻辑错误",
                 "files": ["src/logic.py"], "interfaces": ["process(d) -> Result"], "dependencies": ["validate"]},
                {"name": "error_handling", "description": "完善错误处理与日志",
                 "files": ["src/errors.py", "src/logger.py"], "interfaces": ["AppError", "log_error(e)"], "dependencies": ["fix_logic"]},
            ]
        }
    if "api" in text_lower or "接口" in text_lower:
        return {
            "summary": "设计和实现 REST API 接口层",
            "subtasks": [
                {"name": "models", "description": "定义数据模型和序列化",
                 "files": ["src/models.py"], "interfaces": ["User", "to_dict()"], "dependencies": []},
                {"name": "routes", "description": "实现路由和请求处理",
                 "files": ["src/routes.py"], "interfaces": ["register_routes(app)"], "dependencies": ["models"]},
                {"name": "middleware", "description": "认证、限流、日志中间件",
                 "files": ["src/middleware.py"], "interfaces": ["auth_middleware", "rate_limit"], "dependencies": []},
                {"name": "handlers", "description": "业务逻辑处理器",
                 "files": ["src/handlers.py"], "interfaces": ["create_user(d)", "get_user(id)"], "dependencies": ["models", "routes"]},
                {"name": "tests", "description": "API 集成测试",
                 "files": ["tests/test_api.py"], "interfaces": [], "dependencies": ["handlers"]},
            ]
        }
    return {
        "summary": f"实现功能：{issue_text[:50]}",
        "subtasks": [
            {"name": "core", "description": "实现核心逻辑",
             "files": ["src/core.py"], "interfaces": ["Core.run()"], "dependencies": []},
            {"name": "integration", "description": "集成到现有系统",
             "files": ["src/integration.py"], "interfaces": ["integrate(ctx) -> bool"], "dependencies": ["core"]},
            {"name": "tests", "description": "单元测试和集成测试",
             "files": ["tests/test_core.py"], "interfaces": [], "dependencies": ["core"]},
        ]
    }


class DynamicStubArchitect(Architect):
    def __init__(self, config: TeamConfig | None = None):
        super().__init__(config or TeamConfig(),
                         StubLLMClient({"default": "dynamic"}))
        self.config = config or TeamConfig()

    def run(self, issue_text: str) -> tuple[str, list[Subtask], object]:
        from src.llm import LLMResponse
        plan_data = _generate_stub_plan(issue_text)
        summary = plan_data["summary"]
        subtasks = [Subtask.from_dict(s) for s in plan_data["subtasks"]]
        tokens = len(issue_text) // 4 + len(str(plan_data)) // 4
        return summary, subtasks, LLMResponse(
            content=json.dumps(plan_data, ensure_ascii=False),
            tokens_in=tokens, tokens_out=tokens, model="stub",
        )


def create_stub_architect(plan_cache: dict[str, list[Subtask]] | None = None
                          ) -> Architect:
    return DynamicStubArchitect()
