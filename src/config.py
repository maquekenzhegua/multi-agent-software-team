from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from enum import Enum


class ModelProvider(Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"


@dataclass
class ModelSpec:
    provider: ModelProvider
    model_id: str


DEFAULT_ROLE_MODELS: dict[str, ModelSpec] = {
    "architect": ModelSpec(ModelProvider.ANTHROPIC, "claude-opus-4-7"),
    "coder": ModelSpec(ModelProvider.ANTHROPIC, "claude-sonnet-4-7"),
    "reviewer": ModelSpec(ModelProvider.OPENAI, "gpt-5.4"),
    "tester": ModelSpec(ModelProvider.GOOGLE, "gemini-2.5-pro"),
    "merge_coord": ModelSpec(ModelProvider.ANTHROPIC, "claude-haiku-4-5"),
}


@dataclass
class BudgetCeiling:
    max_tokens_per_role: dict[str, int] = field(default_factory=lambda: {
        "architect": 20000,
        "coder": 15000,
        "reviewer": 10000,
        "tester": 8000,
        "merge_coord": 5000,
    })
    max_total_tokens: int = 120000
    max_cost_cents: int = 500


@dataclass
class TeamConfig:
    role_models: dict[str, ModelSpec] = field(default_factory=lambda: dict(DEFAULT_ROLE_MODELS))
    budget: BudgetCeiling = field(default_factory=BudgetCeiling)
    max_coders: int = 8
    default_coders: int = 4
    worktree_base: str = field(default_factory=lambda: os.path.join(tempfile.gettempdir(), "agent-worktrees"))
    board_path: str = "team_board.jsonl"
    inject_bug_rate: float = 0.0
    execute_tests: bool = False

    @classmethod
    def from_env(cls) -> TeamConfig:
        config = cls()
        for role, env_key in [("architect", "TEAM_ARCHITECT_MODEL"),
                               ("coder", "TEAM_CODER_MODEL"),
                               ("reviewer", "TEAM_REVIEWER_MODEL"),
                               ("tester", "TEAM_TESTER_MODEL")]:
            model_id = os.environ.get(env_key, "")
            if model_id:
                provider = ModelProvider.ANTHROPIC
                if "gpt" in model_id.lower():
                    provider = ModelProvider.OPENAI
                elif "gemini" in model_id.lower():
                    provider = ModelProvider.GOOGLE
                config.role_models[role] = ModelSpec(provider, model_id)
        max_coders = os.environ.get("TEAM_MAX_CODERS", "")
        if max_coders:
            config.max_coders = int(max_coders)
        inject_rate = os.environ.get("TEAM_INJECT_BUG_RATE", "")
        if inject_rate:
            config.inject_bug_rate = float(inject_rate)
        return config
