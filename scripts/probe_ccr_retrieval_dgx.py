#!/usr/bin/env python3
"""Probe whether the proxy resolves CCR retrieval calls under different response formats."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib import request

PROXY_URL = os.getenv("HEADROOM_PROXY_URL", "http://127.0.0.1:8788")
MODEL = os.getenv("HEADROOM_AGENT_MODEL_NAME", "deepseek/deepseek-v4-flash")
API_KEY = os.getenv("HEADROOM_AGENT_API_KEY") or os.getenv("OPENROUTER_API_KEY", "")
PROXY_LOG = Path(os.getenv("HEADROOM_PROXY_LOG", str(Path.home() / ".headroom" / "proxy.log")))

PARAGRAPH = (
    "Context compression for LLM agents reduces the volume of information in an agent working "
    "memory while preserving task-relevant details. Anchored iterative summarization scores "
    "highest on accuracy across thirty-six thousand engineering messages. ACON reduces memory "
    "usage while preserving task accuracy across several benchmarks. Sliding window reduces "
    "tokens in conversational workloads with low effort. Turn summarization preserves continuity "
    "across long sessions. Retrieval augmented generation acts as context compression in "
    "document-heavy tasks. Context pruning removes low-value spans in agent workflows. "
)

SYSTEM_PROMPT = (
    "You are a discovery subagent. Use only the provided evidence. "
    "Return JSON with keys summary, recommended_next_action, confidence. "
    "The evidence is a JSON document whose evidence_items array holds one excerpt per item."
)


def evidence_payload(items: int) -> str:
    return json.dumps(
        {
            "objective_type": "web_research",
            "evidence_items": [
                {
                    "kind": "document",
                    "rank": index,
                    "source": f"https://example.com/study/{index}",
                    "section": 0,
                    "score": 1.0,
                    "text": PARAGRAPH * 2,
                }
                for index in range(items)
            ],
        },
        ensure_ascii=False,
    )


def log_offset() -> int:
    try:
        return PROXY_LOG.stat().st_size
    except OSError:
        return 0


def log_since(offset: int) -> list[str]:
    try:
        with PROXY_LOG.open("r", encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return [line.rstrip() for line in handle if "CCR" in line or "retriev" in line.lower()]
    except OSError:
        return []


def post_chat(payload: dict[str, object]) -> dict[str, object]:
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{PROXY_URL}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    with request.urlopen(req, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def run(label: str, *, response_format: dict[str, object] | None) -> None:
    payload: dict[str, object] = {
        "model": MODEL,
        "temperature": 0,
        "max_tokens": 2048,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Objective: summarize context compression strategies.\nEvidence JSON:\n{evidence_payload(30)}\n"},
        ],
    }
    if response_format is not None:
        payload["response_format"] = response_format

    offset = log_offset()
    try:
        body = post_chat(payload)
    except Exception as exc:
        print(f"{label}: request_error {exc}")
        return
    time.sleep(1.0)

    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content") or ""
    mentions = [word for word in ("retriev", "compressed", "hash=") if word in content.lower()]
    print(
        f"{label}: finish_reason={choice.get('finish_reason')} "
        f"content_chars={len(content)} tool_calls={bool(message.get('tool_calls'))} "
        f"mentions={mentions}"
    )
    print(f"{label}: content_head={content[:300]!r}")
    for line in log_since(offset):
        print(f"{label}: log {line[:220]}")


def main() -> int:
    print(f"proxy={PROXY_URL} model={MODEL} log={PROXY_LOG}")
    run("A_json_object", response_format={"type": "json_object"})
    run("B_no_response_format", response_format=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
