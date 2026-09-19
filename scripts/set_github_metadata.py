#!/usr/bin/env python3
"""Set GitHub repository metadata for headroom_agent_mcp."""

from __future__ import annotations

import json
from pathlib import Path
from urllib import error, request


ENV_FILE = Path(r"Z:\.hermes\.env")
REPO_NAME = "headroom_agent_mcp"
DESCRIPTION = "Read-only discovery MCP for OpenClaw with optional Headroom-proxied LLM enrichment"
TOPICS = [
    "mcp",
    "model-context-protocol",
    "openclaw",
    "headroom",
    "python",
    "discovery",
    "llm",
    "openai-compatible",
    "code-search",
    "log-analysis",
]


def load_env_value(key: str) -> str:
    """Read a single key from the shared env file without printing its value."""
    if not ENV_FILE.exists():
        raise RuntimeError(f"Missing env file: {ENV_FILE}")
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith(f"{key}="):
            value = raw_line.split("=", 1)[1].strip()
            if value:
                return value
    raise RuntimeError(f"Missing required key in {ENV_FILE}: {key}")


def github_request(token: str, method: str, url: str, payload: dict | None = None) -> dict:
    """Call the GitHub REST API and return parsed JSON."""
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"GitHub API {method} {url} failed: HTTP {exc.code} {body}") from exc


def main() -> int:
    token = load_env_value("GITHUB_TOKEN")
    user = github_request(token, "GET", "https://api.github.com/user")
    owner = user["login"]
    base_url = f"https://api.github.com/repos/{owner}/{REPO_NAME}"

    github_request(token, "PATCH", base_url, {"description": DESCRIPTION})
    topics_payload = github_request(token, "PUT", f"{base_url}/topics", {"names": TOPICS})

    print(f"repo=https://github.com/{owner}/{REPO_NAME}")
    print(f"description={DESCRIPTION}")
    print("topics=" + ", ".join(topics_payload.get("names", [])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
