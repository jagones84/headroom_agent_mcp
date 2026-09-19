"""Measure websearch latency: cold vs warm cache, sequential vs concurrent fetch."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from typing import Any

from headroom_agent_mcp import websearch
from headroom_agent_mcp.cache import default_cache_dir
from headroom_agent_mcp.service import DiscoveryService


def _clear_cache() -> None:
    shutil.rmtree(default_cache_dir(), ignore_errors=True)
    websearch.reset_cache()


def _timed(label: str, action: Callable[[], Any]) -> tuple[Any, float]:
    start = time.perf_counter()
    result = action()
    elapsed = time.perf_counter() - start
    print(f"[INFO] {label}: {elapsed:.2f}s")
    return result, elapsed


def main() -> int:
    query = os.getenv("HEADROOM_WEBSEARCH_PROBE_QUERY", "context compression for llm agents")
    limit = 5
    print(f"[INFO] cache_dir={default_cache_dir()} ttl={os.getenv('HEADROOM_AGENT_CACHE_TTL_SECONDS', 'default')}")

    _clear_cache()
    (search_results, provider), cold_search = _timed(
        "search (cold)", lambda: websearch.search_web(query, limit)
    )
    (_, warm_provider), warm_search = _timed(
        "search (warm)", lambda: websearch.search_web(query, limit)
    )
    print(f"[INFO] provider={provider} warm_provider={warm_provider} results={len(search_results)}")

    urls = [result.url for result in search_results[:limit]]
    if not urls:
        print("[ERROR] no search results to fetch; check BRAVE_API_KEY / TAVILY_API_KEY")
        return 1

    service = DiscoveryService(llm_evidence_char_budget=12000)
    _clear_cache()
    sequential, seq_fetch = _timed(
        f"fetch sequential x{len(urls)}",
        lambda: [service._fetch_url(url) for url in urls],
    )
    _clear_cache()
    concurrent, par_fetch = _timed(f"fetch concurrent x{len(urls)}", lambda: service._fetch_many(urls))
    cached, warm_fetch = _timed(f"fetch cached x{len(urls)}", lambda: service._fetch_many(urls))

    seq_chars = sum(len(text) for text, _ in sequential)
    con_chars = sum(len(text) for text, _ in concurrent)
    same_content = sequential == concurrent == cached
    print(
        f"[INFO] readable chars sequential={seq_chars} concurrent={con_chars} "
        f"same_content={same_content}"
    )
    print(
        f"[RESULT] search cold={cold_search:.2f}s warm={warm_search:.2f}s | "
        f"fetch seq={seq_fetch:.2f}s concurrent={par_fetch:.2f}s cached={warm_fetch:.2f}s"
    )
    return 0 if same_content else 1


if __name__ == "__main__":
    raise SystemExit(main())
