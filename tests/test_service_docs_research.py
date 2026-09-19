from pathlib import Path
from unittest.mock import patch

from headroom_agent_mcp.models import (
    CommandAllowlistProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    ObjectiveType,
)
from headroom_agent_mcp.service import DiscoveryService


def test_docs_research_returns_grounded_findings_from_real_doc_content(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(
        "# Headroom Agent MCP\n"
        "\n"
        "Use HEADROOM_AGENT_API_KEY and HEADROOM_AGENT_BASE_URL to configure the provider.\n"
        "Optional override: HEADROOM_AGENT_MODEL_NAME.\n",
        encoding="utf-8",
    )
    request = DiscoveryRequest(
        objective="Find the environment variables used to configure the MCP",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(readme)],
        query_hints=["HEADROOM_AGENT_API_KEY", "HEADROOM_AGENT_BASE_URL", "environment", "variables"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    assert response.candidate_files
    assert any(
        "headroom_agent_api_key" in finding.lower() or "headroom_agent_base_url" in finding.lower()
        for finding in response.relevant_findings
    )


def test_docs_research_collects_env_template_when_scanning_directory(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Config\n", encoding="utf-8")
    (tmp_path / ".env.template").write_text(
        "HEADROOM_AGENT_API_KEY=\n"
        "HEADROOM_AGENT_BASE_URL=https://openrouter.ai/api/v1\n",
        encoding="utf-8",
    )
    request = DiscoveryRequest(
        objective="Find the environment variables used to configure the MCP",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(tmp_path)],
        query_hints=["HEADROOM_AGENT_API_KEY", "HEADROOM_AGENT_BASE_URL"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=4,
        raw_read_budget=4,
    )

    response = DiscoveryService().run(request)

    candidate_paths = [Path(item.path).name for item in response.candidate_files]
    assert ".env.template" in candidate_paths


def test_docs_research_runs_terminal_commands(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("# Guide\nUse MCP_ENDPOINT to configure the host.\n", encoding="utf-8")
    request = DiscoveryRequest(
        objective="Find the configuration commands and environment variables",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(tmp_path)],
        query_hints=["MCP_ENDPOINT", "configuration"],
        terminal_commands=[["git", "status"]],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_TERMINAL,
        max_files=2,
        max_commands=1,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    assert len(response.commands_run) == 1
    assert response.commands_run[0].command == ["git", "status"]
    assert response.commands_run[0].blocked is False


def test_docs_research_declares_uncertainty_when_large_file_was_truncated(tmp_path: Path) -> None:
    large_file = tmp_path / "big_far.py"
    large_file.write_text(("x" * 21050) + "\nNEEDLE_AT_END = True\n", encoding="utf-8")
    request = DiscoveryRequest(
        objective="Find NEEDLE_AT_END",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(large_file)],
        query_hints=["NEEDLE_AT_END"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    assert response.candidate_files
    assert any("truncated" in item.lower() and "big_far.py" in item for item in response.uncertainties)


def test_docs_research_uses_bounded_file_read_instead_of_path_read_text(tmp_path: Path) -> None:
    readme = tmp_path / "README.md"
    readme.write_text("HEADROOM_AGENT_BASE_URL=http://localhost:8000/v1\n", encoding="utf-8")
    request = DiscoveryRequest(
        objective="Find the configured base URL",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(readme)],
        query_hints=["HEADROOM_AGENT_BASE_URL"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    with patch("headroom_agent_mcp.service.Path.read_text", side_effect=AssertionError("read_text should not be used")):
        response = DiscoveryService().run(request)

    assert response.candidate_files
    assert any("headroom_agent_base_url" in finding.lower() for finding in response.relevant_findings)


def _run_single_file_research(path: Path, needle: str) -> DiscoveryResponse:
    request = DiscoveryRequest(
        objective=f"Find {needle}",
        objective_type=ObjectiveType.DOCS_RESEARCH,
        scope_paths=[str(path)],
        query_hints=[needle],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )
    return DiscoveryService().run(request)


def _joined_snippets(response: DiscoveryResponse) -> str:
    return "\n".join(snippet.snippet for snippet in response.small_snippets)


def test_docs_research_keeps_match_visible_when_needle_is_at_end_of_long_line(tmp_path: Path) -> None:
    needle = "NEEDLE_AT_THE_END_OF_A_LONG_LINE"
    long_line = tmp_path / "bundle.js"
    long_line.write_text(("x" * 8000) + needle + "\n", encoding="utf-8")

    response = _run_single_file_research(long_line, needle)

    assert response.candidate_files
    assert response.small_snippets
    assert needle in _joined_snippets(response)
    assert not any("truncated" in item.lower() for item in response.uncertainties)


def test_docs_research_keeps_match_visible_in_minified_single_line_json(tmp_path: Path) -> None:
    needle = "MCP_SECRET_TOKEN"
    minified = tmp_path / "data.min.json"
    minified.write_text('{"payload":"' + ("y" * 3000) + '","token":"' + needle + '"}\n', encoding="utf-8")

    response = _run_single_file_research(minified, needle)

    assert response.candidate_files
    assert needle in _joined_snippets(response)
    assert not any("truncated" in item.lower() for item in response.uncertainties)


def test_docs_research_keeps_prefix_snippet_for_normal_multiline_file(tmp_path: Path) -> None:
    needle = "MCP_ENDPOINT"
    source = tmp_path / "guide.md"
    source.write_text(
        "# Guide\n"
        f"Set {needle} to configure the host.\n"
        "Then restart the service.\n",
        encoding="utf-8",
    )

    response = _run_single_file_research(source, needle)

    joined = _joined_snippets(response)
    assert needle in joined
    assert "…" not in joined
