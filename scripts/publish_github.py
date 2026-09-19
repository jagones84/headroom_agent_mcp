#!/usr/bin/env python3
"""Create/publish the repository to GitHub using a token from Z:\\.hermes\\.env."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib import error, request


REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(r"Z:\.hermes\.env")
REPO_NAME = "headroom_agent_mcp"
DESCRIPTION = "Discovery-focused MCP overlay for OpenClaw with optional Headroom-proxied subagent workflow"


def load_env_value(key: str) -> str:
    """Read a single key from the shared DGX env file without printing its value."""
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


def ensure_repo_exists(token: str, owner: str) -> None:
    """Create the repository if it does not already exist."""
    try:
        github_request(token, "GET", f"https://api.github.com/repos/{owner}/{REPO_NAME}")
        print(f"repo_exists owner={owner} name={REPO_NAME}")
        return
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
    github_request(
        token,
        "POST",
        "https://api.github.com/user/repos",
        {
            "name": REPO_NAME,
            "description": DESCRIPTION,
            "private": False,
            "has_issues": True,
            "has_projects": False,
            "has_wiki": False,
        },
    )
    print(f"repo_created owner={owner} name={REPO_NAME}")


def run_git(args: list[str], *, extra_env: dict[str, str] | None = None) -> None:
    """Run git/gh commands from the repo root."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    subprocess.run(args, cwd=REPO_ROOT, env=env, check=True)


def main() -> int:
    token = load_env_value("GITHUB_TOKEN")
    user = github_request(token, "GET", "https://api.github.com/user")
    owner = user["login"]
    ensure_repo_exists(token, owner)

    remote_url = f"https://github.com/{owner}/{REPO_NAME}.git"
    remotes = subprocess.run(
        ["git", "remote"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if "origin" in remotes:
        run_git(["git", "remote", "set-url", "origin", remote_url])
    else:
        run_git(["git", "remote", "add", "origin", remote_url])

    gh_env = {"GH_TOKEN": token}
    run_git(["gh", "auth", "setup-git"], extra_env=gh_env)
    run_git(["git", "push", "-u", "origin", "main"], extra_env=gh_env)
    print(f"repo_published=https://github.com/{owner}/{REPO_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
