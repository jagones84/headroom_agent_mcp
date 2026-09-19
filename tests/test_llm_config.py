import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from headroom_agent_mcp.config import HeadroomAgentConfig, LLMProfile
from headroom_agent_mcp.llm import (
    OpenAICompatibleLLMClient,
    UnresolvedCCRRetrievalError,
    extract_json_object,
)
from headroom_agent_mcp.models import (
    CandidateFile,
    CommandAllowlistProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    ObjectiveType,
)
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


def test_service_defaults_llm_output_language_to_english(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("Configurazione: MCP_ENDPOINT e MCP_TOKEN.\n", encoding="utf-8")
    llm_client = _FakeLLMClient()
    service = DiscoveryService(llm_client=llm_client, default_model_profile="openrouter")
    request = DiscoveryRequest(
        objective="Cosa c'e' qui?",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(tmp_path)],
        query_hints=["MCP_ENDPOINT", "MCP_TOKEN"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )

    service.run(request)

    assert "respond in english" in llm_client.system_prompts[0].lower()


def test_service_honors_explicit_response_language_for_llm(tmp_path: Path) -> None:
    target = tmp_path / "README.md"
    target.write_text("Configurazione: MCP_ENDPOINT e MCP_TOKEN.\n", encoding="utf-8")
    llm_client = _FakeLLMClient()
    service = DiscoveryService(llm_client=llm_client, default_model_profile="openrouter")
    request = DiscoveryRequest(
        objective="Cosa c'e' qui?",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(tmp_path)],
        query_hints=["MCP_ENDPOINT", "MCP_TOKEN"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        response_language="it",
    )

    service.run(request)

    assert "respond in it" in llm_client.system_prompts[0].lower()


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


def test_extract_json_object_strips_markdown_fence() -> None:
    fenced = '```json\n{"summary": "fenced answer", "confidence": "high"}\n```'

    assert extract_json_object(fenced)["summary"] == "fenced answer"


def test_extract_json_object_ignores_surrounding_prose() -> None:
    body = 'Here is the result:\n{"summary": "inner", "confidence": "low"}\nHope that helps.'

    assert extract_json_object(body)["summary"] == "inner"


def test_extract_json_object_rejects_non_object_payloads() -> None:
    with pytest.raises(ValueError):
        extract_json_object("[1, 2, 3]")


def test_llm_client_sends_max_tokens_and_omits_response_format_by_default() -> None:
    config = HeadroomAgentConfig(
        headroom_proxy_url="http://127.0.0.1:8788",
        llm_profiles={
            "openrouter": LLMProfile(
                model="deepseek/deepseek-v4-flash",
                base_url="https://openrouter.ai/api/v1",
                api_key_env=None,
                require_api_key=False,
                use_headroom_proxy=True,
            )
        },
    )
    client = OpenAICompatibleLLMClient(config=config)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": '```json\n{"summary": "ok"}\n```'}}]}

    with patch("headroom_agent_mcp.llm.httpx.post", return_value=response) as post_mock:
        result = client.complete_json("openrouter", system_prompt="sys", user_prompt="usr")

    assert result["summary"] == "ok"
    payload = post_mock.call_args.kwargs["json"]
    assert payload["max_tokens"] == 2048
    assert "response_format" not in payload


def test_llm_client_keeps_response_format_when_profile_opts_in() -> None:
    config = HeadroomAgentConfig(
        llm_profiles={
            "local": LLMProfile(
                model="local-model",
                base_url="http://127.0.0.1:8000/v1",
                api_key_env=None,
                require_api_key=False,
                supports_json_response_format=True,
                max_tokens=512,
            )
        }
    )
    client = OpenAICompatibleLLMClient(config=config)
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"choices": [{"message": {"content": "{\"summary\": \"ok\"}"}}]}

    with patch("headroom_agent_mcp.llm.httpx.post", return_value=response) as post_mock:
        client.complete_json("local", system_prompt="sys", user_prompt="usr")

    payload = post_mock.call_args.kwargs["json"]
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["max_tokens"] == 512


def _proxied_client() -> OpenAICompatibleLLMClient:
    config = HeadroomAgentConfig(
        headroom_proxy_url="http://127.0.0.1:8788",
        llm_profiles={
            "openrouter": LLMProfile(
                model="deepseek/deepseek-v4-flash",
                base_url="https://openrouter.ai/api/v1",
                api_key_env=None,
                require_api_key=False,
                use_headroom_proxy=True,
            )
        },
    )
    return OpenAICompatibleLLMClient(config=config)


def test_llm_client_raises_typed_error_for_unresolved_ccr_retrieval() -> None:
    client = _proxied_client()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [{"function": {"name": "headroom_retrieve"}} for _ in range(5)],
                },
            }
        ]
    }

    with patch("headroom_agent_mcp.llm.httpx.post", return_value=response):
        with pytest.raises(UnresolvedCCRRetrievalError) as excinfo:
            client.complete_json("openrouter", system_prompt="sys", user_prompt="usr")

    assert excinfo.value.tool_names == ["headroom_retrieve"] * 5


def test_llm_client_keeps_generic_error_for_non_ccr_tool_calls() -> None:
    client = _proxied_client()
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "some_other_tool"}}],
                },
            }
        ]
    }

    with patch("headroom_agent_mcp.llm.httpx.post", return_value=response):
        with pytest.raises(RuntimeError) as excinfo:
            client.complete_json("openrouter", system_prompt="sys", user_prompt="usr")

    assert not isinstance(excinfo.value, UnresolvedCCRRetrievalError)


class _FlakyLLMClient(_FakeLLMClient):
    def __init__(self, errors: list[Exception]) -> None:
        super().__init__()
        self.errors = errors

    def complete_json(self, profile_name: str, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
        self.calls.append(profile_name)
        self.system_prompts.append(system_prompt)
        self.user_prompts.append(user_prompt)
        if self.errors:
            raise self.errors.pop(0)
        return self.payload


def _codebase_request(tmp_path: Path) -> DiscoveryRequest:
    (tmp_path / "service.py").write_text(
        "def resolve_auth_route() -> str:\n    return 'ok'\n", encoding="utf-8"
    )
    return DiscoveryRequest(
        objective="Find auth routing",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )


def test_service_retries_once_with_smaller_evidence_after_unresolved_ccr() -> None:
    from headroom_agent_mcp.service import EvidenceDocument

    llm_client = _FlakyLLMClient(
        [UnresolvedCCRRetrievalError(["headroom_retrieve"] * 5, "tool_calls")]
    )
    service = DiscoveryService(
        llm_client=llm_client,
        default_model_profile="openrouter",
        llm_evidence_char_budget=12000,
    )
    service._llm_documents = [
        EvidenceDocument(path="big.py", text=("needle paragraph with auth routing. " * 600), score=1.0)
    ]
    request = DiscoveryRequest(
        objective="Find auth routing",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )
    response = DiscoveryResponse(
        summary="mechanical summary",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        relevant_findings=["finding"],
        candidate_files=[CandidateFile(path="big.py", reason="match", score=1.0)],
        candidate_symbols=[],
        small_snippets=[],
        commands_run=[],
        raw_reads_needed_by_parent=[],
        uncertainties=[],
        recommended_next_action="",
        confidence="medium",
    )

    enriched = service._maybe_enrich_with_llm(request, response, "openrouter")

    assert enriched.llm_enriched is True
    assert llm_client.calls == ["openrouter", "openrouter"]
    assert len(llm_client.user_prompts[1]) < len(llm_client.user_prompts[0])


def test_service_reports_honest_error_when_ccr_retry_also_fails(tmp_path: Path) -> None:
    llm_client = _FlakyLLMClient(
        [
            UnresolvedCCRRetrievalError(["headroom_retrieve"] * 5, "tool_calls"),
            UnresolvedCCRRetrievalError(["headroom_retrieve"] * 3, "tool_calls"),
        ]
    )
    service = DiscoveryService(llm_client=llm_client, default_model_profile="openrouter")

    response = service.run(_codebase_request(tmp_path))

    assert response.llm_enriched is False
    assert llm_client.calls == ["openrouter", "openrouter"]
    assert "reduced-evidence retry" in (response.llm_error or "")


def test_format_llm_evidence_limits_documents_when_max_documents_is_set() -> None:
    from headroom_agent_mcp.service import EvidenceDocument

    service = DiscoveryService(llm_evidence_char_budget=12000)
    service._llm_documents = [
        EvidenceDocument(path=f"doc{index}.py", text=("body text. " * 182), score=1.0)
        for index in range(4)
    ]
    response = DiscoveryResponse(
        summary="s",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        relevant_findings=[],
        candidate_files=[],
        candidate_symbols=[],
        small_snippets=[],
        commands_run=[],
        raw_reads_needed_by_parent=[],
        uncertainties=[],
        recommended_next_action="",
        confidence="medium",
    )

    full = json.loads(service._format_llm_evidence(response))
    lean = json.loads(service._format_llm_evidence(response, 6000, max_documents=1))

    full_sources = {item.get("source") for item in full["evidence_items"] if item.get("kind") == "document"}
    lean_sources = {item.get("source") for item in lean["evidence_items"] if item.get("kind") == "document"}
    assert full_sources == {"doc0.py", "doc1.py", "doc2.py", "doc3.py"}
    assert lean_sources == {"doc0.py"}
    assert len(lean["evidence_items"]) < len(full["evidence_items"])
