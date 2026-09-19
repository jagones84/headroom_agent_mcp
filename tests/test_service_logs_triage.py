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


def test_logs_triage_uses_configured_command_profile_to_block_non_listed_commands(tmp_path: Path) -> None:
    log_file = tmp_path / "server.log"
    log_file.write_text("[ERROR] startup timeout\n", encoding="utf-8")
    service = DiscoveryService(
        command_profiles={
            CommandAllowlistProfile.SAFE_TERMINAL: [["git", "status"]],
        }
    )
    request = DiscoveryRequest(
        objective="Explain why startup fails",
        objective_type=ObjectiveType.LOGS_TRIAGE,
        scope_paths=[str(log_file)],
        terminal_commands=[["ls"]],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_TERMINAL,
        max_files=2,
        raw_read_budget=2,
    )

    response = service.run(request)

    assert response.commands_run
    assert response.commands_run[0].blocked is True
    assert "active profile configuration" in response.commands_run[0].stderr.lower()


def test_logs_triage_uses_query_hints_for_warning_only_logs(tmp_path: Path) -> None:
    log_file = tmp_path / "warnings.log"
    log_file.write_text(
        "[INFO] boot ok\n"
        "[WARNING] PyTorch was not found\n"
        "[WARN] fallback to cpu mode\n",
        encoding="utf-8",
    )
    request = DiscoveryRequest(
        objective="Explain warning-only startup degradation",
        objective_type=ObjectiveType.LOGS_TRIAGE,
        scope_paths=[str(log_file)],
        query_hints=["warning", "warn", "not found"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    assert any("pytorch was not found" in finding.lower() for finding in response.relevant_findings)


def test_logs_triage_ignores_test_fixture_logs_when_real_logs_exist(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "tests" / "fixtures"
    fixtures_dir.mkdir(parents=True)
    (fixtures_dir / "logger.py").write_text(
        'FIXTURE = "[ERROR] database connection timeout"\n',
        encoding="utf-8",
    )
    real_log = tmp_path / "server.log"
    real_log.write_text("[ERROR] real production outage on node 7\n", encoding="utf-8")
    request = DiscoveryRequest(
        objective="Explain the production outage",
        objective_type=ObjectiveType.LOGS_TRIAGE,
        scope_paths=[str(tmp_path)],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=8,
        raw_read_budget=8,
    )

    response = DiscoveryService().run(request)

    joined = " ".join(response.relevant_findings).lower()
    assert "production outage" in joined
    assert "database connection timeout" not in joined
    assert not any("logger.py" in finding for finding in response.relevant_findings)


def test_logs_triage_orders_findings_by_severity_and_dedupes(tmp_path: Path) -> None:
    log_file = tmp_path / "mixed.log"
    log_file.write_text(
        "[INFO] boot ok\n"
        "[WARNING] disk almost full\n"
        "[ERROR] fatal crash\n"
        "[ERROR] fatal crash\n",
        encoding="utf-8",
    )
    request = DiscoveryRequest(
        objective="Explain the crash sequence",
        objective_type=ObjectiveType.LOGS_TRIAGE,
        scope_paths=[str(log_file)],
        query_hints=["boot", "disk", "fatal"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    findings = response.relevant_findings
    assert len(findings) == 3
    assert "fatal crash" in findings[0].lower()
    assert "disk almost full" in findings[1].lower()
    assert "boot ok" in findings[2].lower()


def test_logs_triage_keeps_explicit_test_file_scope(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    explicit_log = tests_dir / "only.log"
    explicit_log.write_text("[ERROR] explicit fixture requested by the caller\n", encoding="utf-8")
    request = DiscoveryRequest(
        objective="Explain the explicit fixture failure",
        objective_type=ObjectiveType.LOGS_TRIAGE,
        scope_paths=[str(explicit_log)],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    assert any("fixture requested by the caller" in finding.lower() for finding in response.relevant_findings)
