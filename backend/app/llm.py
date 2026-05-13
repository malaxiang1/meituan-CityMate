from __future__ import annotations

import json
import re
from typing import Protocol

import httpx

from .config import Settings


class LLMClient(Protocol):
    async def complete_json(self, system: str, user: str) -> dict[str, object]:
        ...


class MockLLMClient:
    async def complete_json(self, system: str, user: str) -> dict[str, object]:
        return {"provider": "mock", "system": system[:80], "input": user[:120]}


class OpenAICompatibleLLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def complete_json(self, system: str, user: str) -> dict[str, object]:
        provider = self.settings.llm_provider.lower()
        if provider == "openai" and not self.settings.openai_api_key:
            return await MockLLMClient().complete_json(system, user)
        url = f"{self.settings.openai_base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.settings.openai_api_key:
            headers["Authorization"] = f"Bearer {self.settings.openai_api_key}"
        payload = {
            "model": self.settings.openai_model,
            "temperature": 0.2,
            "stream": False,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self.settings.request_timeout, headers=headers) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return _loads_json_object(content)


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider.lower() in {"openai", "openai-compatible", "compatible", "ollama", "local"}:
        return OpenAICompatibleLLMClient(settings)
    return MockLLMClient()


def _loads_json_object(content: str) -> dict[str, object]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("LLM response is not a JSON object")
    return value
