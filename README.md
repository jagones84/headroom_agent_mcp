# headroom_agent_mcp

MCP server overlay for `OpenClaw` that runs a **discovery subagent** behind an optional `Headroom` proxy.

It is designed for the cases where Headroom actually helps:
- large docs / README files
- noisy logs and terminal output
- broad codebase discovery before the parent agent reads raw files

It is **not** a final code-editing agent. The parent agent still reads raw files and patches them directly.

## Status

- New standalone repository
- Intended to be published separately from upstream `headroom`
- License: `Apache-2.0`
- Upstream compatibility target: `headroom` + `OpenClaw`

## What It Exposes

One MCP tool:

- `run_discovery`

Use it when the parent agent needs:
- `docs_research`
- `logs_triage`
- `codebase_discovery`

Do **not** use it when:
- you already know the exact 1-3 files to edit
- you need final patch generation
- the input is already small and precise

## Tool Contract

Input highlights:
- `objective`: concrete goal for this run
- `objective_type`: `docs_research` | `logs_triage` | `codebase_discovery`
- `scope_paths`: files, directories, or URLs
- `query_hints`: extra terms to bias search
- `terminal_commands`: optional tokenized safe commands like `["git", "status"]`
- `command_allowlist_profile`: `safe_readonly` or `safe_terminal`

Output highlights:
- `relevant_findings`
- `candidate_files`
- `candidate_symbols`
- `small_snippets`
- `raw_reads_needed_by_parent`
- `recommended_next_action`

The parent agent should treat `raw_reads_needed_by_parent` as the handoff for precise next reads before any edit.

## Architecture

```text
Parent Agent
  -> run_discovery (this MCP)
      -> scoped file/url collection
      -> safe terminal commands
      -> optional LLM summarization
          -> optionally routed through Headroom proxy
  <- structured discovery output

Parent Agent
  -> reads raw target files itself
  -> edits code itself
```

## Why Headroom Is Optional Here

This repo does **not** reimplement Headroom compression logic.

Instead, if you configure the subagent model to talk to a Headroom proxy, the subagent gets automatic compression on its own model traffic while it explores noisy inputs. That keeps the parent agent precise and uncompressed for final edits.

## Configuration

Copy `.env.template` to `.env` or export the variables in your runtime:

- `HEADROOM_AGENT_MODEL_PROVIDER`
- `HEADROOM_AGENT_MODEL_NAME`
- `HEADROOM_AGENT_BASE_URL`
- `HEADROOM_AGENT_API_KEY`
- `HEADROOM_PROXY_URL` (optional)

If `HEADROOM_PROXY_URL` is set, the configured LLM profile can route through it.

## OpenClaw Example

Add a server entry like the example in `config/openclaw.headroom_agent_mcp.example.json`.

The MCP description is intentionally explicit so the parent agent knows:
- when to call it
- what to pass
- what **not** to expect from it

## Development

Windows local test venv:

```bash
python -m venv C:\Users\giova\.venvs\headroom_agent_mcp
C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python -m pip install -e Z:\Repositories\headroom_agent_mcp[dev]
C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python -m pytest Z:\Repositories\headroom_agent_mcp\tests -q
```

DGX smoke scripts:

- `scripts/run_tests_dgx.sh`
- `scripts/smoke_check_dgx.sh`
- `scripts/smoke_openrouter_headroom_dgx.sh`

## License And Attribution

This repository is licensed under `Apache-2.0`, matching the upstream Headroom project.

Why this shape:
- upstream `headroom` is Apache-2.0 licensed
- this repo is a separate overlay/companion project, not a fork that modifies upstream in place
- Apache-2.0 allows separate derivative or companion works as long as the license text is included and attribution/trademark rules are respected

Files added for that:
- `LICENSE`
- `NOTICE`

Upstream reference:
- Headroom: [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom)

This project references Headroom for interoperability and architectural patterns, but does not claim affiliation or endorsement.

## Current Scope

Implemented:
- contract validation
- safe terminal policy
- deterministic discovery service
- optional OpenAI-compatible LLM enrichment
- MCP server and CLI smoke check

Not implemented:
- write/edit tools
- automatic child-process orchestration inside OpenClaw
- remote web search provider integration beyond direct URL fetch
