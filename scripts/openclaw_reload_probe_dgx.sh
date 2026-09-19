#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.nvm/versions/node/v26.8.1/bin:$HOME/.local/bin:$PATH"

OPENCLAW_BIN="$HOME/.local/bin/openclaw"

"$OPENCLAW_BIN" mcp doctor
"$OPENCLAW_BIN" mcp reload
"$OPENCLAW_BIN" mcp probe
