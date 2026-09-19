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
