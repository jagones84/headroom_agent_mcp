# RESEARCH

## Goal

Build a new overlay repo, separate from upstream `headroom`, that exposes a discovery-focused MCP server for `OpenClaw`.

## Source Notes

### Headroom official docs and repo

- Headroom's own `OpenClaw` plugin is a **context engine / proxy path**, not just an on-demand MCP helper:
  - `Z:\Repositories\headroom\plugins\openclaw\README.md`
  - `Z:\Repositories\headroom\plugins\openclaw\src\engine.ts`
  - `Z:\Repositories\headroom\plugins\openclaw\src\plugin\index.ts`
- Headroom official MCP docs explicitly distinguish:
  - `MCP only` = manual/on-demand compression
  - `MCP + proxy` = automatic compression of traffic reaching the subagent LLM
  - `Z:\Repositories\headroom\wiki\mcp.md`

## Design Conclusion

- A plain Headroom MCP is **not enough** for transparent pre-compression of all upstream tool output.
- For this project the useful architecture is:
  - parent agent stays precise
  - discovery subagent can sit behind a Headroom proxy
  - output back to parent is structured and goal-shaped
- The repo therefore implements:
  - one MCP tool `run_discovery`
  - read-only/codebase/docs/logs discovery behavior
  - no direct patching

## Test Strategy

- TDD from contract first:
  - request validation
  - terminal allowlist
  - codebase discovery output
  - logs triage output
  - LLM endpoint resolution
  - MCP server construction smoke
- Then integration/smoke:
  - CLI `--check`
  - DGX test runner
  - DGX OpenRouter/Headroom smoke, if runtime dependencies are available

## Environment Findings

- Windows cannot execute a venv created directly under `Z:\Repositories\headroom_agent_mcp` because the path resolves to UNC and the spawned interpreter fails with `Accesso negato`.
- Working solution:
  - keep repo on `Z:`
  - keep test venv on `C:\Users\giova\.venvs\headroom_agent_mcp`
- DGX has `python3`, but `headroom` is **not** currently on PATH as a global command.
- Real DGX smoke succeeded via repo-local venv:
  - `scripts/run_tests_dgx.sh` -> `10 passed`
  - `scripts/smoke_check_dgx.sh` -> `ok server=headroom_agent_mcp`
  - `scripts/smoke_openrouter_headroom_dgx.sh` -> successful `codebase_discovery` JSON response with model enrichment
- Important runtime lesson:
  - do not run two DGX scripts in parallel against the same venv; it can corrupt pip/bootstrap state
  - the smoke script now uses its own venv path: `~/.venvs/headroom_agent_mcp_smoke`

## Publication / Licensing Notes

- Upstream `headroom` ships with `Apache-2.0` and no upstream `NOTICE` file was found in the checked repo.
- For this new standalone repo, the safe publication shape is:
  - same `Apache-2.0` license text
  - explicit `NOTICE` clarifying this is a separate overlay/companion project
  - `README` section that references upstream for interoperability while avoiding implied endorsement
- GitHub publication is currently blocked only by missing GitHub authentication on this host:
  - `gh` installed
  - `gh auth status` -> not logged in
