from pathlib import Path

from headroom_agent_mcp.models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType
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
