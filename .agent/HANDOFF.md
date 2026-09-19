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

- Suite TDD locale: `10 passed`
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

## Prossimi step consigliati

1. Eseguire `scripts/run_tests_dgx.sh` su DGX.
2. Eseguire `scripts/smoke_check_dgx.sh` per validare boot MCP.
3. Eseguire `scripts/smoke_openrouter_headroom_dgx.sh` con key disponibile.
4. Registrare il server in `openclaw.json` usando `config/openclaw.headroom_agent_mcp.example.json`.
5. Validare una call reale `run_discovery` da OpenClaw con obiettivo `codebase_discovery`.

## Pubblicazione GitHub

- Repo locale git inizializzata in `Z:\Repositories\headroom_agent_mcp\.git`
- `LICENSE` aggiunta come `Apache-2.0`
- `NOTICE` aggiunto per chiarire attribuzione e non-affiliazione rispetto a `headroom`
- `README` aggiornato con sezione `License And Attribution`
- Blocco rimasto:
  - `gh` installato
  - `gh auth status` -> non autenticato
  - il push remoto richiede login GitHub/token valido su questa macchina
