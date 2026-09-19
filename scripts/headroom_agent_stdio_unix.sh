#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT_DIR/.env"
  set +a
elif [[ -f "$HOME/.hermes/.env" ]]; then
  OPENROUTER_API_KEY="$(grep -m1 '^OPENROUTER_API_KEY=' "$HOME/.hermes/.env" | cut -d'=' -f2- || true)"
  if [[ -n "${OPENROUTER_API_KEY:-}" && -z "${HEADROOM_AGENT_API_KEY:-}" ]]; then
    export HEADROOM_AGENT_API_KEY="$OPENROUTER_API_KEY"
  fi
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ -n "${HEADROOM_AGENT_PYTHON:-}" ]]; then
  PYTHON_BIN="$HEADROOM_AGENT_PYTHON"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif [[ -x "$HOME/.venvs/headroom_agent_mcp/bin/python" ]]; then
  PYTHON_BIN="$HOME/.venvs/headroom_agent_mcp/bin/python"
else
  PYTHON_BIN="python3"
fi

exec "$PYTHON_BIN" -m headroom_agent_mcp.server "$@"
