#!/usr/bin/env bash
set -euo pipefail

HEADROOM_VENV="${HEADROOM_VENV:-$HOME/Repositories/headroom/.venv}"
PY="$HEADROOM_VENV/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "ERROR: python not found in $HEADROOM_VENV" >&2
  exit 1
fi

echo "== version =="
VERSION="$("$PY" -c "import importlib.metadata as m; print(m.version('headroom-ai'))")"
echo "headroom-ai $VERSION"

echo "== disk =="
df -h "$HOME" | tail -n 1

echo "== install headroom-ai[ml] ==="
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PY" "headroom-ai[ml]==$VERSION"
else
  "$PY" -m ensurepip --upgrade >/dev/null 2>&1 || true
  "$PY" -m pip install --disable-pip-version-check "headroom-ai[ml]==$VERSION"
fi

echo "== kompress probe =="
"$PY" - <<'PYEOF'
import importlib
mod = importlib.import_module("headroom.transforms")
names = [n for n in dir(mod) if "kompress" in n.lower()]
print("kompress_symbols", names)
for name in names:
    obj = getattr(mod, name)
    if callable(obj) and name.startswith("is_"):
        try:
            print(name, obj())
        except Exception as exc:
            print(name, "error", exc)
PYEOF

echo "== version after =="
"$PY" -c "import importlib.metadata as m; print('headroom-ai', m.version('headroom-ai'))"
