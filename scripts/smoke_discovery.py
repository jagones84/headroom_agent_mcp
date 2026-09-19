#!/usr/bin/env python3
"""Run one discovery request directly, without an MCP host."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from headroom_agent_mcp.config import HeadroomAgentConfig
from headroom_agent_mcp.llm import OpenAICompatibleLLMClient
from headroom_agent_mcp.models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType
from headroom_agent_mcp.service import DiscoveryService


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke run for the discovery service")
    parser.add_argument("--scope", default=".", help="Directory or file scope")
    parser.add_argument(
        "--objective-type",
        default=ObjectiveType.CODEBASE_DISCOVERY.value,
        choices=[item.value for item in ObjectiveType],
    )
    parser.add_argument("--objective", required=True)
    parser.add_argument("--model-profile", default=None)
    args = parser.parse_args()

    config = HeadroomAgentConfig.from_sources()
    llm_client = OpenAICompatibleLLMClient(config=config) if config.llm_profiles else None
    service = DiscoveryService(llm_client=llm_client)
    request = DiscoveryRequest(
        objective=args.objective,
        objective_type=ObjectiveType(args.objective_type),
        scope_paths=[str(Path(args.scope).resolve())],
        query_hints=["mcp", "discovery", "run_discovery"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        model_profile=args.model_profile,
    )
    response = service.run(request)
    print(json.dumps(response.model_dump(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
