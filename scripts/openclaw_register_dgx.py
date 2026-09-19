#!/usr/bin/env python3
"""Register headroom_agent_mcp in the DGX OpenClaw config with backup."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


CONFIG_PATH = Path.home() / ".openclaw" / "openclaw.json"
SERVER_NAME = "headroom_agent_discovery"


def build_server_entry() -> dict[str, object]:
    repo_root = Path.home() / "Repositories" / "headroom_agent_mcp"
    stdio_wrapper = repo_root / "scripts" / "headroom_agent_stdio_unix.sh"
    return {
        "enabled": True,
        "command": str(stdio_wrapper),
        "args": [],
        "cwd": str(repo_root),
        "connectionTimeoutMs": 120000,
    }


def main() -> int:
    raw_text = CONFIG_PATH.read_text(encoding="utf-8")
    data = json.loads(raw_text)

    backup_path = CONFIG_PATH.with_name(
        f"{CONFIG_PATH.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    backup_path.write_text(raw_text, encoding="utf-8")

    mcp_block = data.setdefault("mcp", {})
    servers = mcp_block.setdefault("servers", {})
    existing = servers.get(SERVER_NAME)
    action = "updated" if existing else "added"
    servers[SERVER_NAME] = build_server_entry()

    updated_text = json.dumps(data, indent=2, ensure_ascii=True) + "\n"
    json.loads(updated_text)
    CONFIG_PATH.write_text(updated_text, encoding="utf-8")

    print(f"backup={backup_path}")
    print(f"server={SERVER_NAME}")
    print(f"action={action}")
    print(f"command={servers[SERVER_NAME]['command']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
