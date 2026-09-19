#!/usr/bin/env python3
"""Wire Headroom into OpenClaw.

Adds the official Headroom MCP server (compress/retrieve/stats) launched from the
Headroom repo venv, and points our discovery MCP at the local Headroom proxy so the
subagent's LLM traffic is compressed.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

CONFIG = Path.home() / ".openclaw" / "openclaw.json"
HEADROOM_VENV = Path.home() / "Repositories" / "headroom" / ".venv"
HEADROOM_WORKSPACE = Path.home() / ".headroom"
PROXY_URL = "http://127.0.0.1:8788"
OUR_SERVER = "headroom_agent_discovery"
OFFICIAL_SERVER = "headroom"


def main() -> int:
    """Patch the OpenClaw config in place, keeping a timestamped backup."""
    if not CONFIG.is_file():
        raise SystemExit(f"missing config: {CONFIG}")

    headroom_bin = HEADROOM_VENV / "bin" / "headroom"
    if not headroom_bin.is_file():
        raise SystemExit(f"missing headroom binary: {headroom_bin}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup = CONFIG.with_name(f"{CONFIG.name}.bak-{stamp}-headroom-wire")
    shutil.copy2(CONFIG, backup)

    data = json.loads(CONFIG.read_text(encoding="utf-8"))
    servers = data.setdefault("mcp", {}).setdefault("servers", {})

    servers[OFFICIAL_SERVER] = {
        "enabled": True,
        "command": str(headroom_bin),
        "args": ["mcp", "serve", "--proxy-url", PROXY_URL],
        "env": {"HEADROOM_WORKSPACE_DIR": str(HEADROOM_WORKSPACE)},
        "connectionTimeoutMs": 120000,
    }

    our_server = servers.get(OUR_SERVER)
    if isinstance(our_server, dict):
        our_server.setdefault("env", {})["HEADROOM_PROXY_URL"] = PROXY_URL
    else:
        print(f"warning: {OUR_SERVER} not present; proxy env not injected")

    CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"backup={backup}")
    print(f"official_command={servers[OFFICIAL_SERVER]['command']}")
    print(f"official_args={' '.join(servers[OFFICIAL_SERVER]['args'])}")
    our_env = servers.get(OUR_SERVER, {}).get("env", {})
    print(f"our_proxy_env={our_env.get('HEADROOM_PROXY_URL')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
