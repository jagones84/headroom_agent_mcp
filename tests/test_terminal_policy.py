from headroom_agent_mcp.models import CommandAllowlistProfile
from headroom_agent_mcp.terminal import is_command_allowed


def test_safe_terminal_allows_git_status() -> None:
    assert is_command_allowed(["git", "status"], CommandAllowlistProfile.SAFE_TERMINAL)


def test_safe_terminal_rejects_rm() -> None:
    assert not is_command_allowed(["rm", "-rf", "/"], CommandAllowlistProfile.SAFE_TERMINAL)


def test_safe_readonly_rejects_test_execution() -> None:
    assert not is_command_allowed(["pytest", "-q"], CommandAllowlistProfile.SAFE_READONLY)
