from pathlib import Path

from headroom_agent_mcp.models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType
from headroom_agent_mcp.service import DiscoveryService


def test_codebase_discovery_returns_candidates_and_raw_reads(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "auth.py").write_text(
        "def resolve_auth_route(user_role: str) -> str:\n"
        "    if user_role == 'admin':\n"
        "        return '/admin'\n"
        "    return '/login'\n",
        encoding="utf-8",
    )
    (src_dir / "routes.py").write_text(
        "AUTH_ROUTES = {'login': '/login', 'admin': '/admin'}\n",
        encoding="utf-8",
    )
    request = DiscoveryRequest(
        objective="Find where auth routing is decided",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        query_hints=["auth", "route"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=4,
        raw_read_budget=3,
    )

    response = DiscoveryService().run(request)

    assert response.objective_type is ObjectiveType.CODEBASE_DISCOVERY
    assert response.candidate_files
    assert any("auth.py" in item.path for item in response.candidate_files)
    assert response.candidate_symbols
    assert response.raw_reads_needed_by_parent
    assert response.recommended_next_action


def test_codebase_discovery_skips_egg_info_and_limits_symbols_to_candidate_files(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    egg_info_dir = src_dir / "headroom_agent_mcp.egg-info"
    egg_info_dir.mkdir()

    service_file = src_dir / "service.py"
    service_file.write_text(
        "def resolve_service_logic() -> str:\n"
        "    return 'service logic'\n",
        encoding="utf-8",
    )
    server_file = src_dir / "server.py"
    server_file.write_text(
        "def create_server() -> str:\n"
        "    return 'server'\n",
        encoding="utf-8",
    )
    (egg_info_dir / "SOURCES.txt").write_text(
        "service service service service server server server\n",
        encoding="utf-8",
    )

    request = DiscoveryRequest(
        objective="Find the service server implementation",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        query_hints=["service", "server"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=2,
        raw_read_budget=2,
    )

    response = DiscoveryService().run(request)

    candidate_paths = [item.path for item in response.candidate_files]
    assert all(".egg-info" not in path for path in candidate_paths)
    assert response.candidate_symbols
    assert all(symbol.path in candidate_paths for symbol in response.candidate_symbols)


def test_codebase_discovery_applies_config_defaults_when_request_omits_them(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for index in range(3):
        (src_dir / f"service_{index}.py").write_text(
            f"def resolve_service_{index}() -> str:\n    return 'service {index}'\n",
            encoding="utf-8",
        )

    service = DiscoveryService(request_defaults={"max_files": 1, "raw_read_budget": 1})
    request = DiscoveryRequest(
        objective="Find service implementation",
        objective_type=ObjectiveType.CODEBASE_DISCOVERY,
        scope_paths=[str(tmp_path)],
        query_hints=["service"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
    )

    response = service.run(request)

    assert len(response.candidate_files) == 1
    assert response.raw_reads_needed_by_parent == [response.candidate_files[0].path]
