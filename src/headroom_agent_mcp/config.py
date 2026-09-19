"""Configuration loader for the discovery MCP server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LLMProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: str
    base_url: str
    api_key_env: str
    use_headroom_proxy: bool = False


class HeadroomAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headroom_proxy_url: str | None = None
    llm_profiles: dict[str, LLMProfile] = Field(default_factory=dict)

    @classmethod
    def from_sources(cls, config_path: str | Path | None = None) -> "HeadroomAgentConfig":
        config_file = Path(config_path) if config_path else Path("config/config.yaml")
        yaml_data: dict[str, Any] = {}
        if config_file.exists():
            yaml_data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}

        profiles: dict[str, LLMProfile] = {}
        provider = os.getenv("HEADROOM_AGENT_MODEL_PROVIDER", "openrouter")
        model = os.getenv("HEADROOM_AGENT_MODEL_NAME", "openrouter/deepseek/deepseek-chat")
        base_url = os.getenv("HEADROOM_AGENT_BASE_URL", "https://openrouter.ai/api/v1")
        api_key_env = "HEADROOM_AGENT_API_KEY"
        profiles[provider] = LLMProfile(
            model=model,
            base_url=base_url,
            api_key_env=api_key_env,
            use_headroom_proxy=bool(os.getenv("HEADROOM_PROXY_URL")),
        )

        llm_profiles = yaml_data.get("llm_profiles", {})
        for name, profile_data in llm_profiles.items():
            profiles[name] = LLMProfile.model_validate(profile_data)

        return cls(
            headroom_proxy_url=os.getenv("HEADROOM_PROXY_URL") or yaml_data.get("headroom_proxy_url"),
            llm_profiles=profiles,
        )
