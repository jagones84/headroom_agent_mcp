"""FastMCP server exposing a single goal-shaped discovery tool."""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import HeadroomAgentConfig
from .llm import OpenAICompatibleLLMClient
from .models import DiscoveryRequest
from .service import DiscoveryService


def create_server(config_path: str | Path | None = None) -> FastMCP:
    """Create the MCP server instance."""
    config = HeadroomAgentConfig.from_sources(config_path)
    llm_client = OpenAICompatibleLLMClient(config=config) if config.llm_profiles else None
    service = DiscoveryService(
        llm_client=llm_client,
        default_model_profile=config.default_model_profile,
        request_defaults=config.request_defaults,
        command_profiles=config.command_profiles,
    )
    mcp = FastMCP("headroom_agent_mcp")

    @mcp.tool(
        name="run_discovery",
        annotations={
            "title": "Run Discovery",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    def run_discovery(params: DiscoveryRequest) -> dict:
        """Explore noisy docs, logs, or codebases and return only the evidence a parent agent needs.

        Use this tool when the parent agent needs discovery or triage before reading raw files itself.
        Best cases: docs research, logs/output triage, or codebase discovery over broad scopes.
        Do not use it for final file edits or precise patch generation.

        Inputs:
        - objective: concrete question or goal for this run
        - objective_type: docs_research, logs_triage, or codebase_discovery
        - scope_paths: files, directories, or URLs to inspect
        - query_hints: optional extra terms to bias search/scoring
        - terminal_commands: optional tokenized safe commands, e.g. [["git","status"],["pytest","-q"]]
        """

        return service.run(params).model_dump()

    return mcp


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for smoke checks and stdio serving."""
    parser = argparse.ArgumentParser(description="Headroom-backed discovery MCP server")
    parser.add_argument("--config", default=None, help="Optional config YAML path")
    parser.add_argument("--check", action="store_true", help="Validate config and exit")
    args = parser.parse_args(argv)

    server = create_server(args.config)
    if args.check:
        print(f"ok server={server.name}")
        return 0
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
