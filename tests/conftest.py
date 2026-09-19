"""Shared test setup."""

from __future__ import annotations

import pytest

from headroom_agent_mcp import websearch


@pytest.fixture(autouse=True)
def _no_disk_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite off the real cache directory.

    Every test starts and ends with the cache disabled and its singleton dropped,
    so runs never write to ``~/.headroom/agent_cache`` and one test's cached
    search results cannot leak into the next.
    """
    monkeypatch.setenv("HEADROOM_AGENT_CACHE_TTL_SECONDS", "0")
    websearch.reset_cache()
    yield
    websearch.reset_cache()
