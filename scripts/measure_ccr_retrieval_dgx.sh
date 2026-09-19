#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${HEADROOM_AGENT_PYTHON:-$HOME/.venvs/headroom_agent_mcp/bin/python}"
PROBE_LINE='ccr_retrievals|total_retrievals|global_retrieval_rate|ccr_markers|transforms_applied|savings_percent'

echo "== baseline ccr counters =="
"$PY" "$ROOT_DIR/scripts/inspect_proxy_jsonl_dgx.py" | grep -E "$PROBE_LINE" || true

echo "== web_research smoke through the proxy =="
bash "$ROOT_DIR/scripts/smoke_web_research_dgx.sh"

echo "== after ccr counters =="
"$PY" "$ROOT_DIR/scripts/inspect_proxy_jsonl_dgx.py" | grep -E "$PROBE_LINE" || true
