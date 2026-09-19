#!/usr/bin/env python3
"""Run an OpenClaw agent call and verify headroom_agent_discovery usage."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import uuid
from pathlib import Path


OPENCLAW_BIN = Path.home() / ".local" / "bin" / "openclaw"
REPO_ROOT = Path.home() / "Repositories" / "headroom_agent_mcp"
GATEWAY_ENV = Path.home() / ".openclaw" / "gateway.systemd.env"


def read_gateway_token() -> str:
    for raw_line in GATEWAY_ENV.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("OPENCLAW_GATEWAY_TOKEN="):
            return raw_line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"OPENCLAW_GATEWAY_TOKEN not found in {GATEWAY_ENV}")


def extract_tool_summary(payload: dict[str, object]) -> dict[str, object]:
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return {}
    meta = result.get("meta", {})
    if not isinstance(meta, dict):
        return {}
    tool_summary = meta.get("toolSummary", {})
    return tool_summary if isinstance(tool_summary, dict) else {}


def extract_text(payload: dict[str, object]) -> str:
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return ""
    candidate = result.get("payloads", [])
    if not isinstance(candidate, list):
        return ""
    parts: list[str] = []
    for item in candidate:
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def main() -> int:
    env = os.environ.copy()
    env["PATH"] = (
        f"{Path.home() / '.nvm' / 'versions' / 'node' / 'v26.8.1' / 'bin'}:"
        f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"
    )
    env["OPENCLAW_GATEWAY_TOKEN"] = read_gateway_token()

    prompt = (
        "Use the headroom_agent_discovery MCP tool once. "
        "Objective: find where the MCP tool is registered in this repo and which file the parent "
        "agent should read raw first. Scope only /home/jagones/Repositories/headroom_agent_mcp. "
        "Return a compact answer with tool name, first candidate file, and recommended next raw read."
    )
    session_key = f"agent:coordinator:explicit:headroom-agent-mcp-e2e-{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory(prefix="headroom-openclaw-e2e-") as temp_dir:
        message_path = Path(temp_dir) / "message.txt"
        output_path = Path(temp_dir) / "output.json"
        message_path.write_text(prompt, encoding="utf-8")

        command = [
            str(OPENCLAW_BIN),
            "agent",
            "--agent",
            "coordinator",
            "--session-key",
            session_key,
            "--message-file",
            str(message_path),
            "--json",
        ]

        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        output_path.write_text(completed.stdout, encoding="utf-8")

        if completed.returncode != 0:
            raise RuntimeError(
                f"openclaw agent failed with exit code {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
            )

        payload = json.loads(completed.stdout)
        tool_summary = extract_tool_summary(payload)
        tools = tool_summary.get("tools", [])
        failures = tool_summary.get("failures")
        calls = tool_summary.get("calls")
        text = extract_text(payload)

        if not isinstance(tools, list) or "headroom_agent_discovery__run_discovery" not in tools:
            raise RuntimeError(f"Expected headroom tool in toolSummary, got: {tool_summary}")
        if failures not in (0, "0"):
            raise RuntimeError(f"Tool failures not zero: {tool_summary}")

        print(f"tools={tools}")
        print(f"calls={calls}")
        print(f"failures={failures}")
        print("response_begin")
        print(text.strip())
        print("response_end")
        print(f"json_output={output_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
