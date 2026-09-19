# HANDOFF

## Stato corrente

- Repo creata: `Z:\Repositories\headroom_agent_mcp`
- Target: `OpenClaw`
- Ruolo: subagent MCP per `research + logs triage + codebase discovery`
- Tool MCP esposto: `run_discovery`
- Scope intenzionale: **no code-edit finale**, solo discovery strutturata per il padre

## Cosa e' stato implementato

- Struttura repo con:
  - `src/headroom_agent_mcp/`
  - `tests/`
  - `config/`
  - `scripts/`
  - `.agent/`
- Contratto Pydantic:
  - `DiscoveryRequest`
  - `DiscoveryResponse`
  - enum objective/profile
- Policy terminale allowlist:
  - `safe_readonly`
  - `safe_terminal`
- Servizio discovery:
  - `docs_research`
  - `logs_triage`
  - `codebase_discovery`
- Server MCP (`FastMCP`) con tool:
  - `run_discovery`
- Client LLM OpenAI-compatible opzionale
  - endpoint risolto verso `HEADROOM_PROXY_URL` quando abilitato

## Test e verifica

- Suite TDD locale aggiornata dopo grounding fix + LLM hardening 2026-09-19: `27 passed`
- Comando usato:
  - `C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python -m pytest Z:\Repositories\headroom_agent_mcp\tests -q`
- Nota ambiente:
  - venv su `Z:` fallisce per esecuzione UNC/permessi
  - venv su `C:\Users\giova\.venvs\...` funziona
- DGX:
  - `scripts/run_tests_dgx.sh` -> `10 passed`
  - `scripts/smoke_check_dgx.sh` -> `ok server=headroom_agent_mcp`
  - `scripts/smoke_openrouter_headroom_dgx.sh` -> risposta JSON valida di `codebase_discovery` con ranking file/simboli/snippet

## Blocchi e limiti rilevati

- Su DGX:
  - `python3` presente
  - `headroom` non trovato su PATH globale, ma lo smoke usa il binario della venv repo-local e passa
- Attenzione:
  - non lanciare test DGX e smoke DGX in parallelo sulla stessa venv
  - per questo lo smoke usa `~/.venvs/headroom_agent_mcp_smoke`
- OpenClaw CLI sul DGX:
  - con Node `v24.15.0` fallisce subito con guardrail interno `node:sqlite truncates TEXT at embedded NUL`
  - per `openclaw mcp doctor/reload/probe` serve forzare il PATH a `~/.nvm/versions/node/v26.8.1/bin`
- OpenClaw stdio runtime:
  - il config host blocca `PYTHONPATH` nelle env del server
  - il bootstrap robusto ora passa da `scripts/headroom_agent_stdio_unix.sh`
  - `scripts/openclaw_stdio_dgx.sh` resta come shim compatibile
- Cross-platform 2026-09-19:
  - launcher Windows reale: `scripts/headroom_agent_stdio_windows.py`
  - shim Windows: `scripts/headroom_agent_stdio_windows.cmd`
  - example config Windows: `config/windows.stdio.headroom_agent_mcp.example.json`
  - example OpenClaw/Linux riallineato al launcher Unix generico
  - `HEADROOM_AGENT_PYTHON` supportato per selezionare esplicitamente l'interprete sui due host
- Audit 2026-09-19:
  - F3 fixato: la policy terminale non e' piu' prefix-only; blocca path fuori scope e token `find` distruttivi (`-delete`, `-exec`, ...)
  - F7 fixato: i comandi bloccati vengono restituiti in `commands_run` con `exit_code=-1` e `blocked=true`
  - F1 fixato: il profilo LLM di default viene applicato quando il caller non passa `model_profile`
  - F2 fixato: fallimenti LLM esposti in risposta (`llm_error`, `llm_enriched`, `llm_profile_used`) e loggati su `stderr`
  - F4 fixato: `config/config.yaml` ora alimenta davvero `defaults` e `profiles`
  - F5 fixato: default modello/documentazione allineati a `deepseek/deepseek-v4-flash`
  - F6 fixato in modo sostanziale: esclusi artefatti `.egg-info`, `dist`, `build`, `.pytest_cache`; scoring passato da sottostringhe grezze a tokenizzazione normalizzata
  - F8 fixato: `candidate_symbols` limitato ai file effettivamente esposti in `candidate_files`
  - grounding fix aggiuntivo: l'LLM vede ora `candidate_files` + `candidate_symbols` + `small_snippets` + finding meccanici nel prompt, e non puo' piu' sovrascrivere `relevant_findings` con allucinazioni
  - LLM hardening aggiuntivo:
    - `api_key_env` ora puo' essere `null` per endpoint locali keyless
    - `require_api_key` configurabile per profilo/env
    - `supports_json_response_format` configurabile per provider OpenAI-compatible che rifiutano `response_format`
    - `timeout_seconds` per profilo finalmente applicato davvero dal client HTTP
  - residui NON affrontati in questo passaggio:
    - qualità snippet (`F9`)
    - fixture test trattate come log reali (`F10`)
    - analisi istanze multiple lato host (`F12`)
    - esercizio automatico del proxy Headroom nel wrapper DGX (`F13`)

## Prossimi step consigliati

1. Integrazione live OpenClaw completata il `2026-09-19`:
  - backup creati:
    - `/home/jagones/.openclaw/openclaw.json.bak-20260919-145520`
    - `/home/jagones/.openclaw/openclaw.json.bak-20260919-145659`
  - entry attiva in `~/.openclaw/openclaw.json`:
    - `headroom_agent_discovery`
    - `command=/home/jagones/Repositories/headroom_agent_mcp/scripts/headroom_agent_stdio_unix.sh`
2. Verifica host:
  - `openclaw mcp doctor` -> `headroom_agent_discovery: ok`
  - `openclaw mcp probe` -> `headroom_agent_discovery: 1 tools`
3. Verifica E2E agente:
  - `scripts/openclaw_agent_e2e_dgx.py` -> `tools=['headroom_agent_discovery__run_discovery']`, `calls=1`, `failures=0`
4. Script operativi aggiunti per chiudere il loop live su DGX:
  - `scripts/openclaw_register_dgx.py`
  - `scripts/headroom_agent_stdio_unix.sh`
  - `scripts/openclaw_stdio_dgx.sh`
  - `scripts/headroom_agent_stdio_windows.py`
  - `scripts/headroom_agent_stdio_windows.cmd`
  - `scripts/openclaw_reload_probe_dgx.sh`
  - `scripts/openclaw_agent_e2e_dgx.py`

## Pubblicazione GitHub

- Repo locale git inizializzata in `Z:\Repositories\headroom_agent_mcp\.git`
- `LICENSE` aggiunta come `Apache-2.0`
- `NOTICE` aggiunto per chiarire attribuzione e non-affiliazione rispetto a `headroom`
- `README` aggiornato con sezione `License And Attribution`
- Pubblicazione completata:
  - repo: `https://github.com/jagones84/headroom_agent_mcp`
  - branch pubblicato: `main`
  - remote `origin` configurato verso GitHub
- Metodo usato:
  - token letto da `Z:\.hermes\.env`
  - script operativo: `scripts/publish_github.py`
- Lezione:
  - la connessione GitHub visibile in Trae non garantisce `gh auth status` valido nella shell locale
  - il path affidabile qui e' stato usare `GITHUB_TOKEN` direttamente
