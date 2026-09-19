#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${HEADROOM_AGENT_PYTHON:-$HOME/.venvs/headroom_agent_mcp/bin/python}"
PROXY_URL="${HEADROOM_PROXY_URL:-http://127.0.0.1:8788}"

env_value() {
  grep -m1 "^$1=" "$HOME/.hermes/.env" | cut -d'=' -f2- || true
}

export OPENROUTER_API_KEY="$(env_value OPENROUTER_API_KEY)"
export HEADROOM_AGENT_MODEL_PROVIDER="openrouter"
export HEADROOM_AGENT_MODEL_NAME="${HEADROOM_AGENT_MODEL_NAME:-deepseek/deepseek-v4-flash}"
export HEADROOM_AGENT_API_KEY="$OPENROUTER_API_KEY"
export HEADROOM_PROXY_URL="$PROXY_URL"

curl -fsS "$PROXY_URL/health" >/dev/null

"$PY" "$ROOT_DIR/scripts/probe_ccr_retrieval_dgx.py"
"$PY" "$ROOT_DIR/scripts/headroom_proxy_stats.py" "$PROXY_URL/stats"
