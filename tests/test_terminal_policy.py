from pathlib import Path

from headroom_agent_mcp.models import CommandAllowlistProfile
from headroom_agent_mcp.terminal import is_command_allowed, run_allowed_commands


def test_safe_terminal_allows_git_status() -> None:
    assert is_command_allowed(["git", "status"], CommandAllowlistProfile.SAFE_TERMINAL)


def test_safe_terminal_rejects_rm() -> None:
    assert not is_command_allowed(["rm", "-rf", "/"], CommandAllowlistProfile.SAFE_TERMINAL)


def test_safe_readonly_rejects_test_execution() -> None:
    assert not is_command_allowed(["pytest", "-q"], CommandAllowlistProfile.SAFE_READONLY)


def test_run_allowed_commands_blocks_absolute_path_reads_outside_scope(tmp_path: Path) -> None:
    results = run_allowed_commands(
        [["cat", str(Path("/etc/shadow"))], ["git", "status"]],
        CommandAllowlistProfile.SAFE_TERMINAL,
        cwd=tmp_path,
        max_commands=2,
    )

    assert len(results) == 2
    assert results[0].exit_code == -1
    assert "outside the allowed scope" in results[0].stderr.lower()
    assert results[1].exit_code != -1


def test_run_allowed_commands_blocks_dangerous_find_flags(tmp_path: Path) -> None:
    results = run_allowed_commands(
        [["find", ".", "-delete"], ["find", ".", "-exec", "rm", "-rf", "{}", "+"]],
        CommandAllowlistProfile.SAFE_TERMINAL,
        cwd=tmp_path,
        max_commands=2,
    )

    assert len(results) == 2
    assert all(result.exit_code == -1 for result in results)
    assert all("blocked by policy" in result.stderr.lower() for result in results)
