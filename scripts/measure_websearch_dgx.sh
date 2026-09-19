#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${HEADROOM_AGENT_PYTHON:-$HOME/.venvs/headroom_agent_mcp/bin/python}"

env_value() {
  grep -m1 "^$1=" "$HOME/.hermes/.env" | cut -d'=' -f2- || true
}

export BRAVE_API_KEY="$(env_value BRAVE_API_KEY)"
export TAVILY_API_KEY="$(env_value TAVILY_API_KEY)"
export HEADROOM_AGENT_CACHE_TTL_SECONDS="${HEADROOM_AGENT_CACHE_TTL_SECONDS:-3600}"

"$PY" "$ROOT_DIR/scripts/measure_websearch_dgx.py"
