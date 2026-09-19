# Headroom Proxy on the DGX (domain manual)

Frozen, tested procedure for running the upstream Headroom proxy and routing the delegated
subagent LLM through it. Read this before touching the proxy, the venv or the OpenClaw wiring.

## Architecture (what is compressed, and why)

```text
Parent agent (Trae / OpenClaw)
  -> headroom_agent_discovery__run_discovery        (this repo, MCP tool)
      -> execute the search itself (Brave / Tavily) + fetch + readability extraction
      -> call the DELEGATED LLM
           base_url = HEADROOM_PROXY_URL/v1          (http://127.0.0.1:8788)
             -> Headroom compresses the prompt
                 -> OpenRouter -> deepseek/deepseek-v4-flash
  <- only the small structured discovery output reaches the parent context
```

The proxy sits on the **delegated LLM call**, not on the parent agent. The parent stays exact;
the noisy web payload never enters its context.

## Golden rules

1. The delegated LLM's prompt must be **structured JSON with many items**. Headroom's
   ContentRouter sends JSON arrays to `SmartCrusher` (keeps first/last, errors,
   query-relevant items) and compresses them hard. Prose in the same position saves ~4%.
2. A payload with fewer than ~10 items compresses **0%**. Emit one evidence item per
   document section, never one blob (see `_split_evidence_sections` in `src/.../service.py`).
3. **Never** name the evidence tool `WebSearch`, `WebFetch`, `web_search` or `web_fetch`:
   those are in Headroom's `DEFAULT_VERBATIM_EXCLUDE_TOOLS`, so their output bypasses lossy
   compression entirely.
4. Keep CCR **off** for this subagent (`--no-ccr`, i.e. `HEADROOM_PROXY_CCR=0`, the default).
   The delegated LLM has no retrieval tool, so injected `headroom_retrieve` markers make it
   narrate "let me retrieve the full content" instead of answering.
5. The request timeout must exceed the compression latency: 120s with the proxy, not 45s.
6. Restart the proxy after installing anything into the `headroom` venv. Kompress health is
   reconciled at startup.

## Layout (DGX = `Z:` from the Windows host)

| Thing | Path |
| --- | --- |
| Upstream repo | `/home/jagones/Repositories/headroom` |
| Headroom venv (proxy + MCP live here) | `/home/jagones/Repositories/headroom/.venv` |
| Proxy log | `~/.headroom/proxy.log` |
| Proxy pid | `~/.headroom/proxy.pid` |
| Our repo / subagent venv | `/home/jagones/Repositories/headroom_agent_mcp`, `~/.venvs/headroom_agent_mcp` |
| OpenClaw config | `~/.openclaw/openclaw.json` (timestamped backups next to it) |
| API keys | `~/.hermes/.env` (`OPENROUTER_API_KEY`, `BRAVE_API_KEY`, `TAVILY_API_KEY`) |

Proxy: `http://127.0.0.1:8788`, `--backend openrouter --mode token`.

## Install / update

```bash
bash scripts/setup_headroom_runtime_dgx.sh   # Linux venv + headroom-ai[proxy]
bash scripts/setup_headroom_ml_dgx.sh        # + headroom-ai[ml] (Kompress ML); pulls torch/CUDA
```

Traps already hit here (do not repeat):

- The venv is created with `uv`, so `python -m pip` fails with `No module named pip`.
  Install with `uv pip install --python "$VENV/bin/python" ...` (the setup script does this).
- `headroom-ai[ml]` resolves to `torch>=2.12` plus the full CUDA 13 wheel set (~4 GB download).
  `onnxruntime` was already present, and `is_kompress_available()` returns True for either
  backend, so verify before assuming the ML extra is required.

## Operate

```bash
bash scripts/headroom_proxy_service_dgx.sh start | stop | status
bash scripts/headroom_proxy_stats.py http://127.0.0.1:8788/stats
```

`HEADROOM_PROXY_TARGET_RATIO` (default `0.5`) and `HEADROOM_PROXY_CCR` (default `0`, meaning
`--no-ccr`) are read by the service script. Measured: `HEADROOM_TARGET_RATIO` has **no effect**
on the `router:mixed` path, so it did not reduce the compression ratio.

## Verify

```bash
bash scripts/smoke_web_research_dgx.sh          # web_research end to end + proxy savings
bash scripts/probe_proxy_framings_dgx.sh        # framing benchmark (prose vs JSON N items)
bash scripts/openclaw_reload_probe_dgx.sh       # openclaw mcp doctor/reload/probe
```

Expected `openclaw mcp probe`: `headroom: 3 tools` and `headroom_agent_discovery: 1 tools`.

## Measured results (2026-09-19, `deepseek/deepseek-v4-flash`)

Framing benchmark (real chat path through the proxy):

| Framing | before | after | saved |
| --- | --- | --- | --- |
| prose in the user message | 2,525 | 2,411 | 4.5% |
| JSON, 5 items | 1,547 | 1,547 | 0% |
| JSON, 10 items | 3,067 | 808 | 73.7% |
| JSON, 30 items | 9,187 | 2,368 | 74.2% |

`web_research`, 5 readable sources, one delegated call:

- `--no-ccr` (default): `before=12,938 after=8,091 saved=4,847` → **41.8%**, `llm_enriched=true`,
  rich grounded summary (named strategies, 3.70 vs 3.35/3.44 scores, 26–54%, 95%+).
- CCR enabled: `before=13,235 after=3,890 saved=9,345` → **72.5%**, but the summary degraded
  and ended with "retrieve the full compressed excerpts".

## Rollback

```bash
bash scripts/headroom_proxy_service_dgx.sh stop
# then remove HEADROOM_PROXY_URL / the headroom server entry from ~/.openclaw/openclaw.json
# (restore the newest ~/.openclaw/openclaw.json.bak-* produced by wire_openclaw_headroom_dgx.py)
```

Without `HEADROOM_PROXY_URL` the subagent talks to OpenRouter directly, keeps the 45s timeout
and the 12,000-character evidence budget, and returns to the incompressible prose framing.
