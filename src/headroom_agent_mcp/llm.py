"""OpenAI-compatible LLM client helpers."""

from __future__ import annotations

import json
import os

import httpx

from .config import HeadroomAgentConfig


def extract_json_object(content: str) -> dict[str, object]:
    """Parse the JSON object out of a chat completion body.

    Models frequently wrap the object in a markdown fence or add prose around it,
    so the first object is extracted instead of requiring the body to be pure JSON.
    This keeps the caller working without a forced `response_format`.

    Sources:
    - https://api-docs.deepseek.com/guides/json_mode (JSON Output: the model is
      told to emit JSON through the prompt, so the body still needs parsing)
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response carried no text content")
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])

    if not isinstance(parsed, dict):
        raise ValueError("LLM response is not a JSON object")
    return parsed


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
            "max_tokens": profile.max_tokens,
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
        body = response.json()
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            tool_names = [
                (call.get("function") or {}).get("name") or call.get("name")
                for call in (message.get("tool_calls") or [])
            ]
            raise RuntimeError(
                "LLM returned no text content "
                f"(finish_reason={choice.get('finish_reason')!r}, tool_calls={tool_names})"
            )
        return extract_json_object(content)
