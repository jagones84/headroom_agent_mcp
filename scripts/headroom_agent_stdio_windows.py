"""Windows stdio bootstrap for headroom_agent_mcp."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> int:
    root_dir = Path(__file__).resolve().parent.parent
    _load_env_file(root_dir / ".env")

    src_dir = root_dir / "src"
    sys.path.insert(0, str(src_dir))

    from headroom_agent_mcp.server import main as server_main

    return server_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
