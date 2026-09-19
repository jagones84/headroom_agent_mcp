#!/usr/bin/env python3
"""Probe proxy compression across payload framings using the real chat path."""

from __future__ import annotations

import json
import os
import time
from urllib import request

PROXY_URL = os.getenv("HEADROOM_PROXY_URL", "http://127.0.0.1:8788")
MODEL = os.getenv("HEADROOM_AGENT_MODEL_NAME", "deepseek/deepseek-v4-flash")
API_KEY = os.getenv("HEADROOM_AGENT_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")

PARAGRAPH = (
    "Context compression for LLM agents reduces the volume of information in an agent working "
    "memory while preserving task-relevant details. Anchored iterative summarization scores "
    "highest on accuracy across thirty-six thousand engineering messages. ACON reduces memory "
    "usage while preserving task accuracy across several benchmarks. Sliding window reduces "
    "tokens in conversational workloads with low effort. Turn summarization preserves continuity "
    "across long sessions. Retrieval augmented generation acts as context compression in "
    "document-heavy tasks. Context pruning removes low-value spans in agent workflows. "
)
PROSE = "\n".join(f"[section {index}] {PARAGRAPH}" for index in range(20))


def documents(count: int) -> list[dict[str, object]]:
    return [
        {
            "path": f"https://example.com/study/{index}",
            "title": f"Context compression study {index}",
            "snippet": PARAGRAPH[:180],
            "content": PARAGRAPH * 2,
        }
        for index in range(count)
    ]


def chunked_documents(count: int, chunks_per_document: int) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for index in range(count):
        for chunk in range(chunks_per_document):
            items.append(
                {
                    "path": f"https://example.com/study/{index}",
                    "chunk": chunk,
                    "content": PARAGRAPH,
                }
            )
    return items


def post_chat(messages: list[dict[str, object]]) -> None:
    payload = {"model": MODEL, "temperature": 0, "max_tokens": 64, "messages": messages}
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{PROXY_URL}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    with request.urlopen(req, timeout=300) as response:
        response.read()


def last_request_log() -> dict[str, object]:
    with request.urlopen(f"{PROXY_URL}/stats", timeout=60) as response:
        data = json.loads(response.read().decode("utf-8"))
    logs = data.get("request_logs", [])
    return logs[-1] if logs else {}


def run(label: str, messages: list[dict[str, object]]) -> None:
    try:
        post_chat(messages)
    except Exception as exc:
        print(f"{label}: request_error {exc}")
        return
    time.sleep(0.5)
    row = last_request_log()
    before = row.get("input_tokens_original") or 0
    after = row.get("input_tokens_optimized") or 0
    saved = row.get("tokens_saved") or 0
    percent = round(100 * saved / before, 1) if before else 0.0
    print(
        f"{label}: before={before} after={after} saved={saved} "
        f"({percent}%) transforms={row.get('transforms_applied')}"
    )


def evidence_message(items: list[dict[str, object]]) -> list[dict[str, object]]:
    payload = json.dumps({"objective_type": "web_research", "documents": items}, ensure_ascii=False)
    return [
        {"role": "user", "content": "Analyze this evidence.\n\n" + payload},
    ]


def main() -> int:
    print(f"proxy={PROXY_URL} model={MODEL}")
    run("prose_user", [{"role": "user", "content": f"Analyze this evidence.\n\n{PROSE}"}])
    run("json_user_5docs", evidence_message(documents(5)))
    run("json_user_10docs", evidence_message(documents(10)))
    run("json_user_30docs", evidence_message(documents(30)))
    run("json_user_30chunks", evidence_message(chunked_documents(5, 6)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
