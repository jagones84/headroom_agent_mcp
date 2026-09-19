import json
from pathlib import Path

from headroom_agent_mcp.server import create_server


def test_create_server_returns_fastmcp_instance() -> None:
    server = create_server()

    assert server is not None
    assert server.name == "headroom_agent_mcp"


def test_windows_stdio_launcher_exists_and_targets_module() -> None:
    launcher = Path("scripts/headroom_agent_stdio_windows.py")
    content = launcher.read_text(encoding="utf-8")
    assert "sys.path.insert" in content
    assert "headroom_agent_mcp.server" in content or "headroom_agent_mcp.server import main" in content


def test_unix_stdio_launcher_exists_and_targets_module() -> None:
    launcher = Path("scripts/headroom_agent_stdio_unix.sh")
    content = launcher.read_text(encoding="utf-8")
    assert "PYTHONPATH" in content
    assert "headroom_agent_mcp.server" in content


def test_windows_example_config_exists_and_has_stdio_server() -> None:
    config_path = Path("config/windows.stdio.headroom_agent_mcp.example.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert "mcpServers" in payload
    assert "headroom_agent_discovery" in payload["mcpServers"]
    server = payload["mcpServers"]["headroom_agent_discovery"]
    assert server["command"] == "python"
    assert server["args"][0].endswith("scripts\\headroom_agent_stdio_windows.py")


def test_openclaw_example_uses_unix_stdio_launcher() -> None:
    config_path = Path("config/openclaw.headroom_agent_mcp.example.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    server = payload["mcp"]["servers"]["headroom_agent_discovery"]
    assert server["command"].endswith("scripts/headroom_agent_stdio_unix.sh")
