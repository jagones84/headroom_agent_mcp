#!/usr/bin/env bash
set -euo pipefail

HEADROOM_REPO="${HEADROOM_REPO:-$HOME/Repositories/headroom}"
HEADROOM_VENV="$HEADROOM_REPO/.venv"
STUB_BACKUP="$HEADROOM_REPO/.venv.windows-stub.bak-20260919"
UV_BIN="$HOME/.local/bin/uv"

if [[ -d "$HEADROOM_VENV" && ! -x "$HEADROOM_VENV/bin/python" ]]; then
  if [[ ! -e "$STUB_BACKUP" ]]; then
    mv "$HEADROOM_VENV" "$STUB_BACKUP"
    echo "moved_windows_stub=$STUB_BACKUP"
  else
    rm -rf "$HEADROOM_VENV"
  fi
fi

if [[ -x "$UV_BIN" ]]; then
  "$UV_BIN" venv "$HEADROOM_VENV"
  "$UV_BIN" pip install --python "$HEADROOM_VENV/bin/python" "headroom-ai[proxy]"
else
  python3 -m venv "$HEADROOM_VENV"
  "$HEADROOM_VENV/bin/python" -m pip install --upgrade pip >/dev/null
  "$HEADROOM_VENV/bin/python" -m pip install "headroom-ai[proxy]"
fi

"$HEADROOM_VENV/bin/headroom" --help >/dev/null
echo "OK venv=$HEADROOM_VENV"
