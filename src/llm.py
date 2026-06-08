from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from src.config import ModelProvider, ModelSpec
from src.retry import retry


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class LLMClient:
    def __init__(self, provider: ModelProvider, api_key: str | None = None):
        self.provider = provider
        self.api_key = api_key or self._resolve_key(provider)

    @staticmethod
    def _resolve_key(provider: ModelProvider) -> str:
        key_map = {
            ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
            ModelProvider.OPENAI: "OPENAI_API_KEY",
            ModelProvider.GOOGLE: "GOOGLE_API_KEY",
        }
        key = os.environ.get(key_map[provider], "")
        if not key:
            raise ValueError(f"缺少 {key_map[provider]} 环境变量，请设置后重试")
        return key

    @retry(max_attempts=3, base_delay=1.0, backoff=2.0, max_delay=15.0)
    def chat(self, system: str, user: str, model: str,
             max_tokens: int = 4096) -> LLMResponse:
        if self.provider == ModelProvider.ANTHROPIC:
            return self._anthropic_chat(system, user, model, max_tokens)
        elif self.provider == ModelProvider.OPENAI:
            return self._openai_chat(system, user, model, max_tokens)
        elif self.provider == ModelProvider.GOOGLE:
            return self._google_chat(system, user, model, max_tokens)
        raise ValueError(f"未知供应商: {self.provider}")

    def _anthropic_chat(self, system: str, user: str, model: str,
                        max_tokens: int) -> LLMResponse:
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return LLMResponse(
            content=msg.content[0].text,
            tokens_in=msg.usage.input_tokens,
            tokens_out=msg.usage.output_tokens,
            model=model,
        )

    def _openai_chat(self, system: str, user: str, model: str,
                     max_tokens: int) -> LLMResponse:
        import openai
        client = openai.OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            tokens_in=resp.usage.prompt_tokens if resp.usage else 0,
            tokens_out=resp.usage.completion_tokens if resp.usage else 0,
            model=model,
        )

    def _google_chat(self, system: str, user: str, model: str,
                     max_tokens: int) -> LLMResponse:
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        instance = genai.GenerativeModel(model)
        prompt = f"{system}\n\n{user}" if system else user
        resp = instance.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=max_tokens,
            ),
        )
        usage = resp.usage_metadata if hasattr(resp, "usage_metadata") else None
        return LLMResponse(
            content=resp.text or "",
            tokens_in=usage.prompt_token_count if usage else 0,
            tokens_out=usage.candidates_token_count if usage else 0,
            model=model,
        )


class StubLLMClient(LLMClient):
    """测试用 stub 客户端，不调用真实 API"""

    def __init__(self, canned_responses: dict[str, str] | None = None):
        self.canned = canned_responses or {}

    def chat(self, system: str, user: str, model: str,
             max_tokens: int = 4096) -> LLMResponse:
        key = (system[:40] + user[:40]).lower()
        content = self.canned.get(key, self.canned.get("default", "[stub response]"))
        return LLMResponse(
            content=content,
            tokens_in=len(system) // 4 + len(user) // 4,
            tokens_out=len(content) // 4,
            model=model,
        )


class LLMFactory:
    _clients: dict[ModelProvider, LLMClient] = {}

    @classmethod
    def get(cls, spec: ModelSpec, api_key: str | None = None) -> LLMClient:
        key = (spec.provider, api_key or "")
        if key not in cls._clients:
            cls._clients[key] = LLMClient(spec.provider, api_key)
        return cls._clients[key]

    @classmethod
    def reset(cls) -> None:
        cls._clients.clear()
