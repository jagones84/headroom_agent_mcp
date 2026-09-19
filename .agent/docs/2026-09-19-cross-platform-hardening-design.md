# Cross-Platform Hardening Design

Date: 2026-09-19
Repo: `Z:\Repositories\headroom_agent_mcp`
Scope: make `headroom_agent_mcp` generic, configurable, and runnable on both Windows and Linux/DGX hosts.

## Goal

Turn the current MCP into a cross-platform package that:
- works on Windows and Linux/DGX
- stays configurable per host without hardcoding DGX-only assumptions
- keeps Headroom proxy usage optional and env-driven
- ships host-specific launchers only as thin wrappers around the same Python core

## Non-Goals

- no rearchitecture of the MCP protocol contract
- no Windows-specific IDE host integration beyond shipping a working launcher/example config
- no forced proxy runtime when `HEADROOM_PROXY_URL` is absent

## Chosen Approach

Use a Python core plus thin host wrappers.

Why:
- one behavioral core keeps MCP logic consistent across hosts
- shell/batch wrappers handle env bootstrap and path differences cheaply
- Windows and Linux hosts get explicit entrypoints instead of implicit DGX-only behavior

## Architecture

### Core

The Python package remains the source of truth:
- config loading
- request defaults
- command policy
- discovery logic
- optional LLM enrichment

### Launchers

Ship minimal launchers:
- Linux/DGX: `scripts/openclaw_stdio_dgx.sh`
- Windows: a new stdio launcher under `scripts/` using native Windows shell semantics

Launcher responsibilities only:
- locate repo root
- load `.env` if present
- export `PYTHONPATH` to `src`
- start the package module

The launcher must not contain discovery logic, ranking logic, or policy logic.

### Configuration

Configuration must be generic:
- `.env.template` documents portable env vars only
- `config/config.yaml` contains defaults/profile policy, not DGX-only values
- example host configs are split by platform/host type

### Proxy Behavior

Proxy remains optional:
- if `HEADROOM_PROXY_URL` is present, the configured LLM profile may route through it
- if absent, the LLM uses the configured provider endpoint directly

This keeps the MCP usable on fresh Windows installs, Linux hosts, and DGX without requiring a local Headroom proxy.

## Implementation Slices

1. Add Windows stdio launcher.
2. Remove DGX-only assumptions from docs/examples where they leak into the generic path.
3. Split example configs into Linux/DGX and Windows-oriented variants if needed.
4. Add tests that prove cross-platform config/bootstrap assumptions stay generic.
5. Re-run Python test suite and validate the DGX path still works.

## Validation

Must pass:
- `python -m pytest tests -q` on Windows workspace
- existing DGX/OpenClaw path must remain valid
- Windows launcher must be syntactically correct and point to the same Python core
- docs/examples must show a generic setup path and not imply DGX-only deployment

## Risks

- Windows subprocess/path behavior differs from Linux, so launcher logic must stay minimal
- host MCP runtimes may sanitize env differently; launcher is safer than relying on host-passed env
- adding too much host logic to wrappers would reintroduce drift

## Acceptance

This design is done when:
- repo contains a real Windows launcher
- config and examples are portable
- proxy is optional, not hardcoded
- tests pass
- DGX path still works
