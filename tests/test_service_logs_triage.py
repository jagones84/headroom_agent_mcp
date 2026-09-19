from pathlib import Path

from headroom_agent_mcp.models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType
from headroom_agent_mcp.service import DiscoveryService


def test_logs_triage_extracts_relevant_errors(tmp_path: Path) -> None:
    log_file = tmp_path / "server.log"
    log_file.write_text(
        "[INFO] boot ok\n"
        "[ERROR] database connection timeout\n"
        "Traceback (most recent call last):\n"
        "  ValueError: bad credentials\n",
        encoding="utf-8",
    )
    request = DiscoveryRequest(
        objective="Explain why startup fails",
        objective_type=ObjectiveType.LOGS_TRIAGE,
        scope_paths=[str(log_file)],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    assert response.objective_type is ObjectiveType.LOGS_TRIAGE
    assert response.relevant_findings
    assert any("timeout" in finding.lower() or "credentials" in finding.lower() for finding in response.relevant_findings)
    assert response.raw_reads_needed_by_parent
    assert response.uncertainties
