from headroom_agent_mcp.server import create_server


def test_create_server_returns_fastmcp_instance() -> None:
    server = create_server()

    assert server is not None
