"""Configuration loader for the discovery MCP server."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from .models import CommandAllowlistProfile, ObjectiveType


class LLMProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    model: str
    base_url: str
    api_key_env: str
    use_headroom_proxy: bool = False


class RequestDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    objective_type: ObjectiveType = ObjectiveType.CODEBASE_DISCOVERY
    command_allowlist_profile: CommandAllowlistProfile = CommandAllowlistProfile.SAFE_READONLY
    max_files: int = 8
    max_commands: int = 4
    raw_read_budget: int = 4
    return_snippets: bool = True
    max_snippet_chars: int = 400


class HeadroomAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headroom_proxy_url: str | None = None
    llm_profiles: dict[str, LLMProfile] = Field(default_factory=dict)
    request_defaults: RequestDefaults = Field(default_factory=RequestDefaults)
    command_profiles: dict[CommandAllowlistProfile, list[list[str]]] = Field(default_factory=dict)
    default_model_profile: str | None = None

    @staticmethod
    def _tokenize_profile_commands(raw_profiles: dict[str, Any]) -> dict[CommandAllowlistProfile, list[list[str]]]:
        parsed: dict[CommandAllowlistProfile, list[list[str]]] = {}
        for profile_name, profile_payload in raw_profiles.items():
            profile = CommandAllowlistProfile(profile_name)
            commands: list[list[str]] = []
            for command in profile_payload.get("commands", []):
                if isinstance(command, str):
                    tokens = command.split()
                    if tokens:
                        commands.append(tokens)
            parsed[profile] = commands
        return parsed

    @classmethod
    def from_sources(cls, config_path: str | Path | None = None) -> "HeadroomAgentConfig":
        config_file = Path(config_path) if config_path else Path("config/config.yaml")
        yaml_data: dict[str, Any] = {}
        if config_file.exists():
            yaml_data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}

        profiles: dict[str, LLMProfile] = {}
        provider = os.getenv("HEADROOM_AGENT_MODEL_PROVIDER", "openrouter")
        model = os.getenv("HEADROOM_AGENT_MODEL_NAME", "deepseek/deepseek-v4-flash")
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

        defaults = RequestDefaults.model_validate(yaml_data.get("defaults", {}))
        command_profiles = cls._tokenize_profile_commands(yaml_data.get("profiles", {}))

        return cls(
            headroom_proxy_url=os.getenv("HEADROOM_PROXY_URL") or yaml_data.get("headroom_proxy_url"),
            llm_profiles=profiles,
            request_defaults=defaults,
            command_profiles=command_profiles,
            default_model_profile=provider if provider in profiles else None,
        )
