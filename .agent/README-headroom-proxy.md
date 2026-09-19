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
4. Keep **CCR on** (default) and let the proxy run the retrieval loop. Per upstream
   `wiki/ccr.md` "*The client never sees CCR tool calls — they're handled transparently*":
   the proxy injects `headroom_retrieve`, the model calls it, the proxy resolves it and
   continues the turn. **Do not write a client-side retrieve loop** (the CCR store is
   proxy-local; the client cannot redeem the calls itself).
5. **Never force `response_format: json_object`.** Measured: with it set, the delegated model
   echoed the compressed table back instead of answering (`content` came back `null` on the
   wire, then a 2,539-char echo of the evidence). Ask for JSON in the prompt and parse
   tolerantly instead (`extract_json_object`).
6. Always send `max_tokens`: upstream DeepSeek documents that JSON Output "may occasionally
   return empty content" (<https://api-docs.deepseek.com/guides/json_mode>), and an unbounded
   body can be cut mid-JSON.
7. The request timeout must exceed the compression latency: 120s with the proxy, not 45s.
8. Restart the proxy after installing anything into the `headroom` venv. Kompress health is
   reconciled at startup.
9. The proxy resolves at most **`ccr_max_retrieval_rounds` (default 3, `headroom/proxy/models.py:208`)**
   continuation rounds per turn, and **no CLI flag, env var, or settings-registry key overrides it**
   (only `no_ccr`, `lossless`, `ccr_inline_resolve` for the response path, `no_ccr_proactive_expansion`).
   Past the cap the proxy hands the still-open `headroom_retrieve` calls back to the client, which
   surfaces as `finish_reason='tool_calls'` with no text content. The client handles exactly this
   shape: `UnresolvedCCRRetrievalError` (only when *every* pending call is `headroom_retrieve`) triggers
   **one** retry with metadata-only evidence (`max_documents=0`, halved budget). Metadata carries no
   document sections, so the proxy emits no `<<ccr:>>` markers, injects no tool
   (`headroom/ccr/tool_injection.py` injects only when `scan_for_markers` finds compressed content),
   and the model answers from what is present. Measured live: first attempt 10 open calls →
   retry answered with a 1,187-char grounded summary (`llm_enriched=true`).

## Layout (DGX = `Z:` from the Windows host)

| Thing | Path |
| --- | --- |
| Upstream repo | `/home/jagones/Repositories/headroom` |
| Headroom venv (proxy + MCP live here) | `/home/jagones/Repositories/headroom/.venv` |
| Proxy log | `~/.headroom/proxy.log` |
| Proxy request log (JSONL) | `~/.headroom/proxy.jsonl` |
| CCR store (retrieval cache) | `~/.headroom/ccr_store.db` |
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
bash scripts/headroom_proxy_service_dgx.sh start | start-trace | start-no-ccr | stop | status
bash scripts/headroom_proxy_stats.py http://127.0.0.1:8788/stats
```

- `start` — the live default: CCR on, `--log-file ~/.headroom/proxy.jsonl`.
- `start-trace` — CCR on **plus** `--log-messages`, so the JSONL carries
  `request_messages` / `response_content`. Use it to see what the model actually received.
  It logs prompt content, so treat the file as sensitive.
- `start-no-ccr` — conservative single-shot mode, no retrieval round trip.

Two official flags in the JSONL that answer "did the model retrieve?":

- `transforms_applied` — e.g. `["router:mixed:0.18"]`, the compression strategy and ratio.
- `request_messages` — the compressed blocks with `<<ccr:hash,...>>` markers.

`HEADROOM_PROXY_TARGET_RATIO` (default `0.5`) and `HEADROOM_PROXY_CCR` (default `1`) are read by
the service script. Measured: `HEADROOM_TARGET_RATIO` has **no effect** on the `router:mixed`
path, so it did not reduce the compression ratio.

## Verify

```bash
bash scripts/smoke_web_research_dgx.sh          # web_research end to end + proxy savings
bash scripts/probe_proxy_framings_dgx.sh        # framing benchmark (prose vs JSON N items)
bash scripts/probe_ccr_retrieval_dgx.sh         # CCR behaviour with/without response_format
bash scripts/measure_ccr_retrieval_dgx.sh       # CCR counters before/after one smoke run
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

Response-format probe (same 30-item payload, `probe_ccr_retrieval_dgx.sh`):

| Request | finish_reason | content | result |
| --- | --- | --- | --- |
| `response_format=json_object` | `stop`, no tool call | 2,539 chars | **echoed the compressed table**, no answer |
| no `response_format` | `stop`, no tool call | 919 chars | proper JSON summary |

`web_research`, 5 readable sources, one delegated call:

- CCR on (live default): `before=13,991 after=3,499 saved=10,492` → **75.0%**, `llm_enriched=true`,
  grounded summary naming the strategies and their numbers.
- Same run traced (`start-trace`): `transforms_applied=["router:mixed:0.18"]`, 40 `<<ccr:>>`
  markers in the request, `optimization_latency_ms=2768`, `total_latency_ms=43631` — the extra
  ~40s is the retrieval round trip.
- CCR proof: `toin.total_retrievals` `0 -> 1` and `compression.ccr_retrievals` `42 -> 48`
  across that single call, i.e. the proxy did resolve a `headroom_retrieve` call.
- CCR off (`start-no-ccr`): `before=12,938 after=8,091 saved=4,847` → 41.8%, also a good answer,
  but a single upstream round trip.
- Forcing `response_format=json_object` with CCR on: the client raised
  `LLM returned no text content (finish_reason='stop', tool_calls=[...])` because the upstream
  content was `null` — this is the failure that rule 5 removes.

## Rollback

```bash
bash scripts/headroom_proxy_service_dgx.sh stop
# then remove HEADROOM_PROXY_URL / the headroom server entry from ~/.openclaw/openclaw.json
# (restore the newest ~/.openclaw/openclaw.json.bak-* produced by wire_openclaw_headroom_dgx.py)
```

Without `HEADROOM_PROXY_URL` the subagent talks to OpenRouter directly, keeps the 45s timeout
and the 12,000-character evidence budget, and returns to the incompressible prose framing.
