# headroom_agent_mcp

Read-only discovery MCP for `OpenClaw` and other agent hosts, with optional `Headroom`-proxied LLM enrichment.

It is designed for the cases where Headroom actually helps:
- large docs / README files
- noisy logs and terminal output
- broad codebase discovery before the parent agent reads raw files
- web research, where the fetched page text stays behind the Headroom proxy instead of eating the parent context

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
- `web_research`

Do **not** use it when:
- you already know the exact 1-3 files to edit
- you need final patch generation
- the input is already small and precise

## Tool Contract

Input highlights:
- `objective`: concrete goal for this run
- `objective_type`: `docs_research` | `logs_triage` | `codebase_discovery` | `web_research`
- `scope_paths`: files, directories, or URLs
  URL fetches are bounded and only the first 20,000 characters of each source are inspected.
- `query_hints`: extra terms to bias search
- `terminal_commands`: optional tokenized safe commands like `["git", "status"]`
- `command_allowlist_profile`: `safe_readonly` or `safe_terminal`
- `response_language`: optional output language for LLM enrichment; default `en`
- `search_results_limit`: `web_research` only, 1-10 results per query; default `5`
- `search_provider`: `web_research` only, `brave` | `tavily` | auto-detect from the environment

The tool accepts the fields either **flat** (recommended) or bundled inside a legacy `params` object.
Both forms are valid, so existing callers keep working:

```json
{ "objective": "Find the auth check", "objective_type": "codebase_discovery", "scope_paths": ["src/"] }
```

```json
{ "params": { "objective": "Find the auth check", "objective_type": "codebase_discovery" } }
```

`logs_triage` extra behavior:
- test/fixture directories (`tests`, `test`, `__tests__`, `spec`, `specs`) are ignored when real logs exist
- findings are deduplicated and ordered by severity (error > warning > info)
- if the caller explicitly scopes a single file inside a test directory, it is still honored

`web_research` extra behavior:
- the whole search is delegated to this tool: it queries the backend, then fetches every result
- fetched HTML is reduced to readable text (trafilatura when installed, a stdlib HTML parser otherwise) before any preview is built
- `BRAVE_API_KEY` and `TAVILY_API_KEY` are read from the environment; with neither, the run reports an uncertainty instead of inventing sources

Output highlights:
- `relevant_findings`
- `candidate_files`
- `candidate_symbols`
- `small_snippets`
- `uncertainties`
- `commands_run` (blocked commands are returned with `exit_code=-1`, `blocked=true`)
- `raw_reads_needed_by_parent`
- `recommended_next_action`
- `llm_enriched`
- `llm_error`
- `llm_profile_used`

The parent agent should treat `raw_reads_needed_by_parent` as the handoff for precise next reads before any edit.

## Architecture

```text
Parent Agent
  -> run_discovery (this MCP)
      -> scoped file/url collection
      -> safe terminal commands
      -> web search + readability extraction (web_research)
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

How the evidence is framed matters more than the proxy itself. The delegated LLM receives the bulky raw evidence as one JSON item per document section. Measured against a live proxy on the DGX (`scripts/probe_proxy_framings_dgx.sh`, `deepseek/deepseek-v4-flash`):

| Evidence framing | Prompt tokens before | after | saved |
| --- | --- | --- | --- |
| prose block in the user message | 2,525 | 2,411 | 4.5% |
| JSON, 5 items | 1,547 | 1,547 | 0% |
| JSON, 10 items | 3,067 | 808 | 73.7% |
| JSON, 30 items | 9,187 | 2,368 | 74.2% |

Headroom routes JSON arrays to `SmartCrusher`, which keeps first/last, error and query-relevant items and drops the rest. Prose in the same position barely compresses, and a payload with fewer than ~10 items has nothing to discard. That is why the service emits sections, not a text blob.

End to end on `web_research` (5 readable sources, 12,938-token subagent prompt): the proxy reports `tokens_saved=4,847`, `savings_percent=41.8` with `--no-ccr`, and `72.5%` when CCR is enabled. CCR mode is off by default here: the delegated LLM has no retrieval tool, so injected `headroom_retrieve` markers only invite it to ask for content it cannot fetch, which measurably degraded the answer. Enable it with `HEADROOM_PROXY_CCR=1` when the caller does have the Headroom retrieval tools.

## Quick Start

1. Copy `.env.template` to `.env`
2. Install the package in a Python 3.11+ environment
3. Run the smoke check or wire the stdio launcher into your MCP host

Windows:

```bash
python -m venv C:\Users\giova\.venvs\headroom_agent_mcp
C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python -m pip install -e Z:\Repositories\headroom_agent_mcp[dev]
C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python Z:\Repositories\headroom_agent_mcp\scripts\headroom_agent_stdio_windows.py --check
```

Linux / DGX:

```bash
python3 -m venv ~/.venvs/headroom_agent_mcp
~/.venvs/headroom_agent_mcp/bin/python -m pip install -e ~/Repositories/headroom_agent_mcp[dev]
~/Repositories/headroom_agent_mcp/scripts/headroom_agent_stdio_unix.sh --check
```

## Configuration

Copy `.env.template` to `.env` or export the variables in your runtime:

- `HEADROOM_AGENT_PYTHON` (optional explicit interpreter path for launchers)
- `HEADROOM_AGENT_MODEL_PROVIDER`
- `HEADROOM_AGENT_MODEL_NAME`
- `HEADROOM_AGENT_BASE_URL`
- `HEADROOM_AGENT_API_KEY_ENV` (optional alternate env var name for auth)
- `HEADROOM_AGENT_API_KEY`
- `HEADROOM_AGENT_REQUIRE_API_KEY` (`true` by default; set `false` for local keyless endpoints)
- `HEADROOM_AGENT_USE_JSON_RESPONSE_FORMAT` (`true` by default; set `false` for OpenAI-compatible servers that reject `response_format`)
- `HEADROOM_PROXY_URL` (optional)
- `HEADROOM_AGENT_TIMEOUT_SECONDS` (default `45`; `120` when `HEADROOM_PROXY_URL` is set, because compression adds latency)
- `HEADROOM_AGENT_LLM_EVIDENCE_CHARS` (raw evidence characters handed to the delegated LLM; default `12000`, `40000` when `HEADROOM_PROXY_URL` is set)
- `BRAVE_API_KEY` / `TAVILY_API_KEY` (web search backends for `web_research`)

If `HEADROOM_PROXY_URL` is set, the configured LLM profile routes through it, the evidence budget and the request timeout grow, and the proxy compresses the subagent's own prompt before it reaches the provider.

For local OpenAI-compatible endpoints:
- point `HEADROOM_AGENT_BASE_URL` to your local `/v1` server
- set `HEADROOM_AGENT_REQUIRE_API_KEY=false` if the server is keyless
- set `HEADROOM_AGENT_USE_JSON_RESPONSE_FORMAT=false` if the server does not support JSON response formatting
- optionally set `HEADROOM_AGENT_API_KEY_ENV` to a different variable name if the server still wants auth

`config/config.yaml` is live:
- `defaults` are applied when the caller omits optional request fields like `max_files`, `max_commands`, `raw_read_budget`, `return_snippets`, and `command_allowlist_profile`
- `profiles` define the allowed tokenized command prefixes for each command profile
- directory scans also collect common config files without standard suffixes, such as `.env`, `.env.template`, `Dockerfile`, `Makefile`, and `Procfile`

LLM enrichment behavior:
- if an LLM profile exists and the caller does not pass `model_profile`, the server falls back to the configured default profile
- the caller can force the enrichment output language with `response_language`; default is `en`
- LLM failures are exposed in the response via `llm_error` and logged to `stderr` without corrupting the stdio MCP stream
- zero-score candidates are now labeled as fallback candidates instead of claiming keyword overlap that did not happen

Provider selection:
- the active default LLM backend is chosen by `HEADROOM_AGENT_MODEL_PROVIDER`
- the provider-specific settings come from the matching env values such as `HEADROOM_AGENT_MODEL_NAME` and `HEADROOM_AGENT_BASE_URL`
- the MCP caller can override the default per request by passing `model_profile`
- the current `config/config.yaml` only defines command profiles and request defaults; the default repo setup builds the active LLM profile from env

Current retrieval behavior:
- directory scans collect standard source/docs/log files by suffix
- directory scans also collect common config files by name, including `.env`, `.env.template`, `Dockerfile`, `Makefile`, and `Procfile`
- snippet budget is now distributed across top documents in rounds, so one dense file does not starve the rest of the evidence set
- snippet excerpts are centered on the match column, so long single-line sources (minified JS/JSON, long CSV rows, single-line logs) still include the matching term instead of a mute prefix
- local file reads are bounded to the first 20,000 characters per source to cap memory usage and latency
- URL fetches strip boilerplate to readable text first, then bound the result to the LLM evidence budget (`20,000` characters minimum, `40,000` when the proxy is configured)
- when a source is truncated by that cap, the response adds an `uncertainties` warning instead of treating missing later matches as evidence of absence

Launchers:
- Windows stable launcher: `scripts/headroom_agent_stdio_windows.py`
- Windows convenience shim: `scripts/headroom_agent_stdio_windows.cmd`
- Unix/Linux launcher: `scripts/headroom_agent_stdio_unix.sh`
- DGX compatibility shim: `scripts/openclaw_stdio_dgx.sh`

## MCP JSON Templates

Trae / Windows, use the repo `.env` as the source of truth:

```json
{
  "mcpServers": {
    "headroom_agent_discovery": {
      "type": "STDIO",
      "description": "Headroom Agent MCP discovery server",
      "command": "python",
      "args": [
        "Z:\\Repositories\\headroom_agent_mcp\\scripts\\headroom_agent_stdio_windows.py"
      ],
      "env": {}
    }
  }
}
```

Trae / Windows, force the fast Windows IQ4 backend directly from MCP config:

```json
{
  "mcpServers": {
    "headroom_agent_discovery": {
      "type": "STDIO",
      "description": "Headroom Agent MCP discovery server (Windows IQ4 backend)",
      "command": "python",
      "args": [
        "Z:\\Repositories\\headroom_agent_mcp\\scripts\\headroom_agent_stdio_windows.py"
      ],
      "env": {
        "HEADROOM_AGENT_MODEL_PROVIDER": "local",
        "HEADROOM_AGENT_MODEL_NAME": "nex-n2.5-mini-uncensored-iq4xs",
        "HEADROOM_AGENT_BASE_URL": "http://192.168.1.11:8080/v1",
        "HEADROOM_AGENT_REQUIRE_API_KEY": "false",
        "HEADROOM_AGENT_USE_JSON_RESPONSE_FORMAT": "false",
        "HEADROOM_AGENT_TIMEOUT_SECONDS": "45"
      }
    }
  }
}
```

If `env` is empty, the launcher loads the repo `.env` and that file decides the active provider.
If `env` contains provider variables, the MCP host overrides the repo defaults for that process.

## OpenClaw Example

Add a server entry like the example in `config/openclaw.headroom_agent_mcp.example.json`.

OpenClaw / Linux:

```json
{
  "mcp": {
    "servers": {
      "headroom_agent_discovery": {
        "enabled": true,
        "command": "/home/jagones/Repositories/headroom_agent_mcp/scripts/headroom_agent_stdio_unix.sh",
        "args": [],
        "cwd": "/home/jagones/Repositories/headroom_agent_mcp",
        "connectionTimeoutMs": 120000
      }
    }
  }
}
```

For Windows hosts, use `config/windows.stdio.headroom_agent_mcp.example.json`.

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
- `scripts/smoke_web_research_dgx.sh` (`web_research` end to end, prints proxy savings)
- `scripts/probe_proxy_framings_dgx.sh` (payload-framing compression benchmark)

DGX Headroom proxy runtime:

- `scripts/setup_headroom_runtime_dgx.sh` (Linux venv for the `headroom` repo + `headroom-ai[proxy]`)
- `scripts/setup_headroom_ml_dgx.sh` (adds `headroom-ai[ml]`, the Kompress ML compressor)
- `scripts/headroom_proxy_service_dgx.sh` `{start|stop|status}` (proxy on `127.0.0.1:8788`)
- `scripts/headroom_proxy_stats.py` (one-line savings summary)
- `scripts/wire_openclaw_headroom_dgx.py` (registers the official `headroom` MCP + `HEADROOM_PROXY_URL` in `~/.openclaw/openclaw.json`)

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
- web search (`brave` / `tavily`) with readability extraction
- MCP server and CLI smoke check

Not implemented:
- write/edit tools
- automatic child-process orchestration inside OpenClaw
- a retrieval tool for the delegated LLM (which is why CCR is off by default on the proxy)
