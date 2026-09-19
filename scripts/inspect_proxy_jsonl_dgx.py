#!/usr/bin/env python3
"""Summarize the proxy JSONL request log and /stats retrieval counters."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib import request

JSONL = Path(os.getenv("HEADROOM_PROXY_JSONL", str(Path.home() / ".headroom" / "proxy.jsonl")))
STATS_URL = os.getenv("HEADROOM_PROXY_STATS_URL", "http://127.0.0.1:8788/stats")
NEEDLE = "headroom_retrieve"


def read_records(limit: int) -> list[dict[str, object]]:
    if not JSONL.exists():
        print(f"jsonl_missing path={JSONL}")
        return []
    lines = [line for line in JSONL.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    records: list[dict[str, object]] = []
    for line in lines[-limit:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            records.append({"__unparsed__": line[:200]})
    return records


def describe(record: dict[str, object]) -> None:
    keys = sorted(record)
    print(f"  keys={keys}")
    for key in (
        "request_id",
        "model",
        "input_tokens_original",
        "input_tokens_optimized",
        "tokens_saved",
        "savings_percent",
        "optimization_latency_ms",
        "total_latency_ms",
        "transforms_applied",
        "savings_breakdown",
        "tags",
        "waste_signals",
    ):
        if key in record:
            print(f"  {key}={json.dumps(record[key], default=str)[:400]}")

    messages = json.dumps(record.get("request_messages"), default=str)
    content = json.dumps(record.get("response_content"), default=str)
    print(
        f"  request_messages_chars={len(messages)} ccr_markers={messages.count('<ccr:')} "
        f"retrieve_tool={messages.count(NEEDLE)}"
    )
    print(f"  response_content_chars={len(content)} retrieve_tool={content.count(NEEDLE)}")
    print(f"  response_content_head={content[:400]!r}")


def main() -> int:
    records = read_records(3)
    print(f"jsonl={JSONL} records_read={len(records)}")
    for index, record in enumerate(records):
        print(f"record[{index}]:")
        describe(record)

    with request.urlopen(STATS_URL, timeout=60) as response:
        raw_stats = response.read().decode("utf-8")
    stats = json.loads(raw_stats)
    print(f"stats_top_keys={sorted(stats)}")
    for section in ("summary", "tokens", "compression", "ccr", "persistent_savings", "feedback_loop", "toin", "latency"):
        value = stats.get(section)
        if isinstance(value, dict):
            interesting = {
                key: item
                for key, item in value.items()
                if "retriev" in key.lower() or "compress" in key.lower() or "saved" in key.lower() or "tool" in key.lower()
            }
            print(f"stats[{section}]={json.dumps(interesting, default=str)[:600]}")
    retrieval_hits = sorted({word for word in re.findall(r"[A-Za-z_]*retriev[A-Za-z_]*", raw_stats, re.IGNORECASE)})
    print(f"stats_retrieval_hits={retrieval_hits[:20]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
