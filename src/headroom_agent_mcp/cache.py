"""Best-effort TTL cache for web search results and fetched pages.

Repeating a discovery objective must not re-pay for the same search call and the
same five fetches. The cache is a plain directory of JSON files, one per key, so
there is no shared index to corrupt and no lock to coordinate. Every operation
fails open: a missing directory, an unreadable file or a half-written entry is
treated as a cache miss, never as an error, because a discovery run must never
depend on the cache being healthy.

Runtime state stays outside the repository, under the same ``~/.headroom``
workspace the proxy already uses for its own state.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_TTL_SECONDS = 3600
DEFAULT_CACHE_DIR_NAME = "agent_cache"


def _env_int(name: str, default: int) -> int:
    """Read an integer from the environment, falling back on anything unparsable."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def default_cache_dir() -> Path:
    """Resolve the cache directory: explicit env override, else the Headroom workspace."""
    override = os.getenv("HEADROOM_AGENT_CACHE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".headroom" / DEFAULT_CACHE_DIR_NAME


class TTLCache:
    """Disk-backed key/value cache where every entry expires on its own clock.

    Entries are stored as ``{"key", "expires_at", "value"}``. The key is kept in
    the file so a hash collision cannot hand back a value written for a different
    lookup. Expired files are removed on read, which keeps the directory bounded
    without a sweeper process.
    """

    def __init__(
        self,
        directory: Path | None = None,
        ttl_seconds: int | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.directory = Path(directory) if directory is not None else default_cache_dir()
        if ttl_seconds is None:
            ttl_seconds = _env_int("HEADROOM_AGENT_CACHE_TTL_SECONDS", DEFAULT_TTL_SECONDS)
        self.ttl_seconds = max(int(ttl_seconds), 0)
        self._now = now or time.time

    @property
    def enabled(self) -> bool:
        """A TTL of zero disables the cache entirely."""
        return self.ttl_seconds > 0

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self.directory / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        """Return the cached value, or ``None`` on miss, expiry or any I/O problem."""
        if not self.enabled:
            return None
        path = self._path(key)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("key") != key:
            return None
        try:
            expires_at = float(payload.get("expires_at", 0))
        except (TypeError, ValueError):
            return None
        if expires_at <= self._now():
            try:
                path.unlink()
            except OSError:
                pass
            return None
        return payload.get("value")

    def set(self, key: str, value: Any) -> None:
        """Store a value. Writes are atomic and silently skipped when disabled."""
        if not self.enabled:
            return
        payload = {"key": key, "expires_at": self._now() + self.ttl_seconds, "value": value}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            target = self._path(key)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, target)
        except OSError:
            return
