#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$HOME/.venvs/headroom_agent_mcp_smoke"
PROXY_PORT="8788"
PROXY_URL="http://127.0.0.1:${PROXY_PORT}"
LOG_FILE="$ROOT_DIR/scripts/headroom_proxy_smoke.log"
PID_FILE="$ROOT_DIR/scripts/headroom_proxy_smoke.pid"

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -e "$ROOT_DIR[dev]" "headroom-ai[proxy]" >/dev/null

OPENROUTER_API_KEY="$(grep -m1 '^OPENROUTER_API_KEY=' "$HOME/.hermes/.env" | cut -d'=' -f2- || true)"
if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "ERROR: OPENROUTER_API_KEY not found in ~/.hermes/.env" >&2
  exit 1
fi

export HEADROOM_AGENT_MODEL_PROVIDER="openrouter"
export HEADROOM_AGENT_MODEL_NAME="deepseek/deepseek-v4-flash"
export HEADROOM_AGENT_BASE_URL="https://openrouter.ai/api/v1"
export HEADROOM_AGENT_API_KEY="$OPENROUTER_API_KEY"
export HEADROOM_PROXY_URL="$PROXY_URL"

"$VENV_DIR/bin/headroom" proxy --backend openrouter --host 127.0.0.1 --port "$PROXY_PORT" >"$LOG_FILE" 2>&1 &
PROXY_PID=$!
echo "$PROXY_PID" >"$PID_FILE"

cleanup() {
  kill "$PROXY_PID" >/dev/null 2>&1 || true
  rm -f "$PID_FILE"
}
trap cleanup EXIT

for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "$PROXY_URL/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "$PROXY_URL/health" >/dev/null 2>&1

"$VENV_DIR/bin/python" "$ROOT_DIR/scripts/smoke_discovery.py" \
  --scope "$ROOT_DIR" \
  --objective "Find where the MCP tool is registered and what the parent should read raw next" \
  --objective-type codebase_discovery \
  --model-profile openrouter
