"""OpenAI-compatible LLM client helpers."""

from __future__ import annotations

import json
import os

import httpx

from .config import HeadroomAgentConfig


class OpenAICompatibleLLMClient:
    """Thin helper around chat-completions style endpoints."""

    def __init__(self, *, config: HeadroomAgentConfig) -> None:
        self.config = config

    def resolve_endpoint(self, profile_name: str) -> str:
        profile = self.config.llm_profiles[profile_name]
        if profile.use_headroom_proxy and self.config.headroom_proxy_url:
            return f"{self.config.headroom_proxy_url.rstrip('/')}/v1"
        return profile.base_url.rstrip("/")

    def complete_json(self, profile_name: str, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        profile = self.config.llm_profiles[profile_name]
        api_key = os.getenv(profile.api_key_env, "")
        if not api_key:
            raise RuntimeError(f"Missing API key in environment variable {profile.api_key_env}")

        endpoint = f"{self.resolve_endpoint(profile_name)}/chat/completions"
        response = httpx.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": profile.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=45.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
