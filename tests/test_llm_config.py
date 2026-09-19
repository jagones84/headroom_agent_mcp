from pathlib import Path
from unittest.mock import Mock, patch

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


def test_llm_client_allows_local_endpoint_without_api_key_when_profile_disables_auth() -> None:
    config = HeadroomAgentConfig(
        llm_profiles={
            "local": LLMProfile(
                model="local-model",
                base_url="http://127.0.0.1:8000/v1",
                api_key_env=None,
                require_api_key=False,
                supports_json_response_format=False,
            )
        }
    )
    client = OpenAICompatibleLLMClient(config=config)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": "{\"summary\":\"ok\"}"}}]}

    with patch("headroom_agent_mcp.llm.httpx.post", return_value=response) as post_mock:
        result = client.complete_json("local", system_prompt="sys", user_prompt="usr")

    assert result["summary"] == "ok"
    kwargs = post_mock.call_args.kwargs
    assert "Authorization" not in kwargs["headers"]
    assert "response_format" not in kwargs["json"]


def test_config_from_sources_can_disable_auth_and_json_response_format(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "llm_profiles:\n"
        "  local:\n"
        "    model: local-model\n"
        "    base_url: http://127.0.0.1:8000/v1\n"
        "    api_key_env: null\n"
        "    require_api_key: false\n"
        "    supports_json_response_format: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HEADROOM_AGENT_MODEL_PROVIDER", "local")
    monkeypatch.setenv("HEADROOM_AGENT_MODEL_NAME", "local-model")
    monkeypatch.setenv("HEADROOM_AGENT_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("HEADROOM_AGENT_REQUIRE_API_KEY", "false")
    monkeypatch.setenv("HEADROOM_AGENT_USE_JSON_RESPONSE_FORMAT", "false")

    config = HeadroomAgentConfig.from_sources(config_path)

    assert config.default_model_profile == "local"
    assert config.llm_profiles["local"].require_api_key is False
    assert config.llm_profiles["local"].supports_json_response_format is False


class _FakeLLMClient:
    def __init__(self, payload: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {"summary": "LLM enriched summary", "confidence": "high"}
        self.error = error
        self.calls: list[str] = []
        self.user_prompts: list[str] = []
        self.system_prompts: list[str] = []

    def complete_json(self, profile_name: str, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        self.calls.append(profile_name)
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
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


def test_service_passes_grounded_evidence_to_llm_and_keeps_mechanical_findings(tmp_path: Path) -> None:
    target = tmp_path / "terminal.py"
    target.write_text(
        "def run_allowed_commands() -> None:\n"
        "    try:\n"
        "        pass\n"
        "    except CalledProcessError:\n"
        "        raise\n",
        encoding="utf-8",
    )
    llm_client = _FakeLLMClient(
        payload={
            "summary": "LLM grounded summary",
            "confidence": "high",
            "relevant_findings": ["invented file src/index.ts"],
        }
    )
    service = DiscoveryService(llm_client=llm_client, default_model_profile="openrouter")
    request = DiscoveryRequest(
        objective="Find subprocess error handling in terminal policy",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        query_hints=["CalledProcessError", "terminal"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )

    response = service.run(request)

    assert llm_client.calls == ["openrouter"]
    assert "CalledProcessError" in llm_client.user_prompts[0]
    assert "terminal.py" in llm_client.user_prompts[0]
    assert "invented file src/index.ts" not in response.relevant_findings
    assert any("terminal.py" in finding for finding in response.relevant_findings)


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
