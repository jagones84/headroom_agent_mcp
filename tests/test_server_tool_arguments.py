import asyncio
import json
from pathlib import Path

import pytest

from headroom_agent_mcp import server as server_module
from headroom_agent_mcp.config import RequestDefaults
from headroom_agent_mcp.server import build_discovery_request, create_server


class _NoLLMConfig:
    """Config stub without LLM profiles, so tool calls stay hermetic and offline."""

    llm_profiles: dict = {}
    default_model_profile = None
    request_defaults = RequestDefaults()
    command_profiles: dict = {}

    @classmethod
    def from_sources(cls, config_path=None):
        return cls()


def _server_without_llm(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server_module, "HeadroomAgentConfig", _NoLLMConfig)
    return create_server()


def _readme(tmp_path: Path) -> Path:
    readme = tmp_path / "README.md"
    readme.write_text("Set MCP_ENDPOINT to configure the host.\n", encoding="utf-8")
    return readme


def _input_schema(server) -> dict:
    tools = asyncio.run(server.list_tools())
    tool = tools[0]
    schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema")
    return schema


def _tool_payload(result) -> dict:
    if isinstance(result, dict):
        return result
    for block in result:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"Unsupported tool result shape: {result!r}")


def test_schema_exposes_flat_fields_and_params(monkeypatch: pytest.MonkeyPatch) -> None:
    server = _server_without_llm(monkeypatch)

    schema = _input_schema(server)
    properties = schema.get("properties", {})

    assert "objective" in properties
    assert "objective_type" in properties
    assert "scope_paths" in properties
    assert "params" in properties


def test_tool_accepts_flat_arguments(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    readme = _readme(tmp_path)
    server = _server_without_llm(monkeypatch)

    result = _tool_payload(
        asyncio.run(
            server.call_tool(
                "run_discovery",
                {
                    "objective": "Find MCP_ENDPOINT",
                    "objective_type": "docs_research",
                    "scope_paths": [str(readme)],
                    "query_hints": ["MCP_ENDPOINT"],
                },
            )
        )
    )

    assert result["candidate_files"]
    assert any("mcp_endpoint" in finding.lower() for finding in result["relevant_findings"])


def test_tool_accepts_nested_params_for_backward_compatibility(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    readme = _readme(tmp_path)
    server = _server_without_llm(monkeypatch)

    result = _tool_payload(
        asyncio.run(
            server.call_tool(
                "run_discovery",
                {
                    "params": {
                        "objective": "Find MCP_ENDPOINT",
                        "objective_type": "docs_research",
                        "scope_paths": [str(readme)],
                        "query_hints": ["MCP_ENDPOINT"],
                    }
                },
            )
        )
    )

    assert result["candidate_files"]


def test_build_discovery_request_prefers_nested_params() -> None:
    request = build_discovery_request(
        params={
            "objective": "Find MCP_ENDPOINT",
            "objective_type": "docs_research",
        },
        objective="ignored when params is present",
    )

    assert request.objective == "Find MCP_ENDPOINT"


def test_build_discovery_request_rejects_payload_without_objective() -> None:
    with pytest.raises(ValueError):
        build_discovery_request(scope_paths=["/tmp"])
