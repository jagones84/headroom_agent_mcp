import json
from pathlib import Path

from headroom_agent_mcp.cache import TTLCache, default_cache_dir


def _clock(start: float = 1000.0) -> dict[str, float]:
    return {"now": start}


def test_ttlcache_round_trips_a_value(tmp_path: Path) -> None:
    cache = TTLCache(tmp_path, ttl_seconds=60)

    cache.set("search::q", {"results": [1, 2, 3]})

    assert cache.get("search::q") == {"results": [1, 2, 3]}
    assert cache.get("search::other") is None


def test_ttlcache_keeps_unicode_payloads_intact(tmp_path: Path) -> None:
    cache = TTLCache(tmp_path, ttl_seconds=60)

    cache.set("k", {"text": "compressione del contesto — naïve"})

    assert cache.get("k") == {"text": "compressione del contesto — naïve"}


def test_ttlcache_expires_and_removes_entries(tmp_path: Path) -> None:
    clock = _clock()
    cache = TTLCache(tmp_path, ttl_seconds=60, now=lambda: clock["now"])
    cache.set("k", "value")

    assert cache.get("k") == "value"

    clock["now"] += 61

    assert cache.get("k") is None
    assert not cache._path("k").exists()


def test_ttlcache_with_zero_ttl_never_touches_the_disk(tmp_path: Path) -> None:
    cache = TTLCache(tmp_path, ttl_seconds=0)

    cache.set("k", "value")

    assert cache.enabled is False
    assert cache.get("k") is None
    assert list(tmp_path.iterdir()) == []


def test_ttlcache_treats_a_corrupt_entry_as_a_miss(tmp_path: Path) -> None:
    cache = TTLCache(tmp_path, ttl_seconds=60)
    cache.set("k", "value")
    cache._path("k").write_text("{ not json", encoding="utf-8")

    assert cache.get("k") is None


def test_ttlcache_rejects_a_payload_written_for_another_key(tmp_path: Path) -> None:
    cache = TTLCache(tmp_path, ttl_seconds=60)
    cache.set("k", "value")
    payload = json.loads(cache._path("k").read_text(encoding="utf-8"))
    payload["key"] = "a different lookup"
    cache._path("k").write_text(json.dumps(payload), encoding="utf-8")

    assert cache.get("k") is None


def test_ttlcache_survives_an_unwritable_directory(tmp_path: Path) -> None:
    blocked = tmp_path / "a-file-not-a-dir"
    blocked.write_text("x", encoding="utf-8")
    cache = TTLCache(blocked / "nested", ttl_seconds=60)

    cache.set("k", "value")

    assert cache.get("k") is None


def test_default_cache_dir_honours_the_env_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HEADROOM_AGENT_CACHE_DIR", str(tmp_path / "custom"))

    assert default_cache_dir() == tmp_path / "custom"
