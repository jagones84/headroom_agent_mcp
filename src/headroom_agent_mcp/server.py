"""FastMCP server exposing a single goal-shaped discovery tool."""

from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .config import HeadroomAgentConfig
from .llm import OpenAICompatibleLLMClient
from .models import CommandAllowlistProfile, DiscoveryRequest, ObjectiveType
from .service import DiscoveryService


def build_discovery_request(
    *,
    params: DiscoveryRequest | dict | None = None,
    objective: str | None = None,
    objective_type: ObjectiveType | str | None = None,
    scope_paths: list[str] | None = None,
    query_hints: list[str] | None = None,
    terminal_commands: list[list[str]] | None = None,
    command_allowlist_profile: CommandAllowlistProfile | str | None = None,
    max_files: int | None = None,
    max_commands: int | None = None,
    return_snippets: bool | None = None,
    raw_read_budget: int | None = None,
    model_profile: str | None = None,
    response_language: str | None = None,
    search_results_limit: int | None = None,
    search_provider: str | None = None,
) -> DiscoveryRequest:
    """Build a discovery request from flat tool arguments or a nested `params` payload.

    `params` keeps backward compatibility with clients (including the OpenClaw runtime)
    that still send the nested envelope. Flat arguments are the friendlier path for agents
    that pass tool arguments directly.
    """
    if params is not None:
        return params if isinstance(params, DiscoveryRequest) else DiscoveryRequest.model_validate(params)

    flat_values = {
        "objective": objective,
        "objective_type": objective_type,
        "scope_paths": scope_paths,
        "query_hints": query_hints,
        "terminal_commands": terminal_commands,
        "command_allowlist_profile": command_allowlist_profile,
        "max_files": max_files,
        "max_commands": max_commands,
        "return_snippets": return_snippets,
        "raw_read_budget": raw_read_budget,
        "model_profile": model_profile,
        "response_language": response_language,
        "search_results_limit": search_results_limit,
        "search_provider": search_provider,
    }
    provided = {key: value for key, value in flat_values.items() if value is not None}
    missing = [key for key in ("objective", "objective_type") if key not in provided]
    if missing:
        raise ValueError(
            "run_discovery requires either `params` or the flat fields "
            f"{', '.join(missing)}. Provide a nested `params` payload or the flat arguments."
        )
    return DiscoveryRequest(**provided)


def create_server(config_path: str | Path | None = None) -> FastMCP:
    """Create the MCP server instance."""
    config = HeadroomAgentConfig.from_sources(config_path)
    llm_client = OpenAICompatibleLLMClient(config=config) if config.llm_profiles else None
    service = DiscoveryService(
        llm_client=llm_client,
        default_model_profile=config.default_model_profile,
        request_defaults=config.request_defaults,
        command_profiles=config.command_profiles,
        llm_evidence_char_budget=config.llm_evidence_char_budget,
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
    def run_discovery(
        params: DiscoveryRequest | None = None,
        objective: str | None = None,
        objective_type: ObjectiveType | None = None,
        scope_paths: list[str] | None = None,
        query_hints: list[str] | None = None,
        terminal_commands: list[list[str]] | None = None,
        command_allowlist_profile: CommandAllowlistProfile | None = None,
        max_files: int | None = None,
        max_commands: int | None = None,
        return_snippets: bool | None = None,
        raw_read_budget: int | None = None,
        model_profile: str | None = None,
        response_language: str | None = None,
        search_results_limit: int | None = None,
        search_provider: str | None = None,
    ) -> dict:
        """Explore noisy docs, logs, or codebases and return only the evidence a parent agent needs.

        Use this tool when the parent agent needs discovery or triage before reading raw files itself.
        Best cases: docs research, logs/output triage, or codebase discovery over broad scopes.
        Do not use it for final file edits or precise patch generation.

        Call it either with flat arguments (recommended) or with the legacy nested `params` envelope.

        Inputs:
        - objective: concrete question or goal for this run
        - objective_type: docs_research, logs_triage, codebase_discovery, or web_research
        - scope_paths: files, directories, or URLs to inspect
          local files and direct URL fetches are inspected with a bounded preview budget
        - query_hints: optional extra terms to bias search/scoring
        - terminal_commands: optional tokenized safe commands, e.g. [["git","status"],["pytest","-q"]]
        - search_results_limit: web results to fetch in `web_research` (1-10, default 5)
        - search_provider: `brave`, `tavily`, or `auto` (default from env)
        - params: optional legacy envelope containing the same fields as a single object

        Notes:
        - `web_research` delegates the whole search: pass the objective, not URLs
        - large files and fetched URLs are truncated to a bounded preview instead of being read fully into memory
        - when truncation happens, the response surfaces it through `uncertainties`
        - HTML pages are converted to readable text before any preview limit, so `<head>` boilerplate never becomes the evidence
        - snippets are excerpted around the matched column, so long single-line sources still contain the matched term
        - in `logs_triage`, test/fixture directories are ignored when real logs exist, and findings are ranked by severity
        - when a Headroom proxy is configured, the evidence sent to the LLM is larger on purpose: Headroom compresses it, this tool does not pre-truncate it
        """

        request = build_discovery_request(
            params=params,
            objective=objective,
            objective_type=objective_type,
            scope_paths=scope_paths,
            query_hints=query_hints,
            terminal_commands=terminal_commands,
            command_allowlist_profile=command_allowlist_profile,
            max_files=max_files,
            max_commands=max_commands,
            return_snippets=return_snippets,
            raw_read_budget=raw_read_budget,
            model_profile=model_profile,
            response_language=response_language,
            search_results_limit=search_results_limit,
            search_provider=search_provider,
        )
        return service.run(request).model_dump()

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
