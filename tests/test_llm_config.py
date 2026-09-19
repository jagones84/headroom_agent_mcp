from pathlib import Path

from headroom_agent_mcp.config import HeadroomAgentConfig, LLMProfile
from headroom_agent_mcp.llm import OpenAICompatibleLLMClient
from headroom_agent_mcp.models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType
from headroom_agent_mcp.service import DiscoveryService


def test_llm_client_prefers_headroom_proxy_when_enabled() -> None:
    config = HeadroomAgentConfig(
        headroom_proxy_url="http://127.0.0.1:8788",
        llm_profiles={
            "openrouter": LLMProfile(
                model="deepseek/deepseek-v4-flash",
                base_url="https://openrouter.ai/api/v1",
                api_key_env="OPENROUTER_API_KEY",
                use_headroom_proxy=True,
            )
        },
    )

    client = OpenAICompatibleLLMClient(config=config)
    resolved = client.resolve_endpoint("openrouter")

    assert resolved == "http://127.0.0.1:8788/v1"


class _FakeLLMClient:
    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {"summary": "LLM enriched summary", "confidence": "high"}
        self.error = error
        self.calls: list[str] = []

    def complete_json(self, profile_name: str, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        self.calls.append(profile_name)
        if self.error:
            raise self.error
        return self.payload


def test_service_uses_default_model_profile_when_request_omits_it(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("def resolve_auth_route() -> str:\n    return 'ok'\n", encoding="utf-8")
    llm_client = _FakeLLMClient()
    service = DiscoveryService(llm_client=llm_client, default_model_profile="openrouter")
    request = DiscoveryRequest(
        objective="Find auth routing",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )

    response = service.run(request)

    assert llm_client.calls == ["openrouter"]
    assert response.llm_enriched is True
    assert response.llm_error is None
    assert response.summary == "LLM enriched summary"


def test_service_surfaces_llm_errors_instead_of_silencing_them(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("def resolve_auth_route() -> str:\n    return 'ok'\n", encoding="utf-8")
    service = DiscoveryService(
        llm_client=_FakeLLMClient(error=RuntimeError("missing profile key")),
        default_model_profile="openrouter",
    )
    request = DiscoveryRequest(
        objective="Find auth routing",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )

    response = service.run(request)

    assert response.llm_enriched is False
    assert response.llm_error == "missing profile key"


def test_config_from_sources_loads_yaml_defaults_profiles_and_slug_model(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "defaults:\n"
        "  command_allowlist_profile: safe_terminal\n"
        "  max_files: 12\n"
        "  max_commands: 6\n"
        "  raw_read_budget: 6\n"
        "  return_snippets: true\n"
        "profiles:\n"
        "  safe_terminal:\n"
        "    commands:\n"
        "      - git status\n"
        "      - git diff --name-only\n",
        encoding="utf-8",
    )

    config = HeadroomAgentConfig.from_sources(config_path)

    assert config.llm_profiles["openrouter"].model == "deepseek/deepseek-v4-flash"
    assert config.request_defaults.max_files == 12
    assert config.request_defaults.max_commands == 6
    assert config.request_defaults.command_allowlist_profile is CommandAllowlistProfile.SAFE_TERMINAL
    assert config.command_profiles[CommandAllowlistProfile.SAFE_TERMINAL] == [
        ["git", "status"],
        ["git", "diff", "--name-only"],
    ]
