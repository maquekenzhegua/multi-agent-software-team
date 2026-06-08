from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from src.config import TeamConfig, ModelSpec, ModelProvider


@dataclass
class RepoConfig:
    ignore_patterns: list[str] = field(default_factory=lambda: ["__pycache__", "*.pyc", ".git"])


@dataclass
class RoleOverride:
    model: str = ""
    max_tokens: int = 0
    parallel: int = 0
    test_command: str = ""


@dataclass
class ProjectConfig:
    name: str = ""
    repo: RepoConfig = field(default_factory=RepoConfig)
    role_overrides: dict[str, RoleOverride] = field(default_factory=dict)
    budget_override: dict[str, int] = field(default_factory=dict)

    def apply_to(self, config: TeamConfig) -> TeamConfig:
        for role, override in self.role_overrides.items():
            if override.model and role in config.role_models:
                provider = ModelProvider.ANTHROPIC
                if "gpt" in override.model.lower():
                    provider = ModelProvider.OPENAI
                elif "gemini" in override.model.lower():
                    provider = ModelProvider.GOOGLE
                config.role_models[role] = ModelSpec(provider, override.model)
            if override.max_tokens and role in config.budget.max_tokens_per_role:
                config.budget.max_tokens_per_role[role] = override.max_tokens
            if override.parallel and role == "coder":
                config.default_coders = override.parallel
        if "max_total_tokens" in self.budget_override:
            config.budget.max_total_tokens = self.budget_override["max_total_tokens"]
        return config


def load_project_config(repo_path: str) -> ProjectConfig | None:
    config_paths = [
        os.path.join(repo_path, ".team.toml"),
        os.path.join(repo_path, ".team.yml"),
        os.path.join(repo_path, ".team.yaml"),
    ]
    for cfg_path in config_paths:
        if os.path.exists(cfg_path):
            return _parse_config(cfg_path)
    return None


def _parse_config(path: str) -> ProjectConfig:
    if path.endswith(".toml"):
        return _parse_toml(path)
    elif path.endswith((".yml", ".yaml")):
        return _parse_yaml(path)
    raise ValueError(f"不支持的配置文件格式: {path}")


def _parse_toml(path: str) -> ProjectConfig:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    with open(path, "rb") as f:
        data = tomllib.load(f)

    cfg = ProjectConfig()
    if "project" in data:
        cfg.name = data["project"].get("name", "")
    if "repo" in data:
        cfg.repo = RepoConfig(
            ignore_patterns=data["repo"].get("ignore_patterns", cfg.repo.ignore_patterns),
        )
    if "roles" in data:
        for role_name, role_data in data["roles"].items():
            cfg.role_overrides[role_name] = RoleOverride(
                model=role_data.get("model", ""),
                max_tokens=role_data.get("max_tokens", 0),
                parallel=role_data.get("parallel", 0),
                test_command=role_data.get("test_command", ""),
            )
    if "budget" in data:
        cfg.budget_override = dict(data["budget"])
    return cfg


def _parse_yaml(path: str) -> ProjectConfig:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    cfg = ProjectConfig()
    if "project" in data:
        cfg.name = data["project"].get("name", "")
    if "repo" in data:
        cfg.repo = RepoConfig(
            ignore_patterns=data["repo"].get("ignore_patterns", cfg.repo.ignore_patterns),
        )
    if "roles" in data:
        for role_name, role_data in data["roles"].items():
            cfg.role_overrides[role_name] = RoleOverride(
                model=role_data.get("model", ""),
                max_tokens=role_data.get("max_tokens", 0),
                parallel=role_data.get("parallel", 0),
                test_command=role_data.get("test_command", ""),
            )
    if "budget" in data:
        cfg.budget_override = dict(data["budget"])
    return cfg
