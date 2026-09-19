#!/usr/bin/env python3
"""Print a compact summary of the Headroom proxy /stats payload."""

from __future__ import annotations

import json
import sys
from urllib import request

DEFAULT_STATS_URL = "http://127.0.0.1:8788/stats"


def main(argv: list[str]) -> int:
    """Fetch the proxy stats endpoint and print the fields that matter for savings."""
    url = argv[1] if len(argv) > 1 else DEFAULT_STATS_URL
    with request.urlopen(url, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    summary = data.get("summary", {})
    compression = summary.get("compression", {})
    tokens = data.get("tokens", {})

    print(f"api_requests={summary.get('api_requests')}")
    print(f"requests_compressed={compression.get('requests_compressed')}")
    print(f"avg_compression_pct={compression.get('avg_compression_pct')}")
    print(f"tokens_saved={tokens.get('saved')}")
    print(f"savings_percent={tokens.get('savings_percent')}")
    print(f"proxy_total_before_compression={tokens.get('proxy_total_before_compression')}")

    for row in data.get("request_logs", [])[-5:]:
        print(
            "request "
            f"{row.get('request_id')} model={row.get('model')} "
            f"before={row.get('input_tokens_original')} after={row.get('input_tokens_optimized')} "
            f"saved={row.get('tokens_saved')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
