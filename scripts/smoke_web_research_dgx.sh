#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${HEADROOM_AGENT_PYTHON:-$HOME/.venvs/headroom_agent_mcp/bin/python}"
PROXY_URL="${HEADROOM_PROXY_URL:-http://127.0.0.1:8788}"
OBJECTIVE="${1:-What is context compression for LLM agents and which strategies are measured effective?}"
REPORT="$ROOT_DIR/.agent/reports/web_research_smoke.json"

env_value() {
  grep -m1 "^$1=" "$HOME/.hermes/.env" | cut -d'=' -f2- || true
}

mkdir -p "$ROOT_DIR/.agent/reports"

export OPENROUTER_API_KEY="$(env_value OPENROUTER_API_KEY)"
export BRAVE_API_KEY="$(env_value BRAVE_API_KEY)"
export TAVILY_API_KEY="$(env_value TAVILY_API_KEY)"

export HEADROOM_AGENT_MODEL_PROVIDER="openrouter"
export HEADROOM_AGENT_MODEL_NAME="deepseek/deepseek-v4-flash"
export HEADROOM_AGENT_BASE_URL="https://openrouter.ai/api/v1"
export HEADROOM_AGENT_API_KEY="$OPENROUTER_API_KEY"
export HEADROOM_PROXY_URL="$PROXY_URL"

curl -fsS "$PROXY_URL/health" >/dev/null

set +e
"$PY" "$ROOT_DIR/scripts/smoke_discovery.py" \
  --scope "$ROOT_DIR" \
  --objective "$OBJECTIVE" \
  --objective-type web_research \
  --query-hints "context compression,LLM agents,strategies" >"$REPORT"
RC=$?
set -e

"$PY" "$ROOT_DIR/scripts/headroom_proxy_stats.py" "$PROXY_URL/stats"

if [[ "$RC" -ne 0 ]]; then
  echo "ERROR: smoke run failed rc=$RC" >&2
  exit "$RC"
fi

echo "OK report=$REPORT"
