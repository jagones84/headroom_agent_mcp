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
        api_key = os.getenv(profile.api_key_env, "") if profile.api_key_env else ""
        if profile.require_api_key and not api_key:
            env_name = profile.api_key_env or "(unset)"
            raise RuntimeError(f"Missing API key in environment variable {env_name}")

        endpoint = f"{self.resolve_endpoint(profile_name)}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": profile.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if profile.supports_json_response_format:
            payload["response_format"] = {"type": "json_object"}
        response = httpx.post(
            endpoint,
            headers=headers,
            json=payload,
            timeout=profile.timeout_seconds,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)
