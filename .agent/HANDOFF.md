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
- Suite locale finale dopo hardening large-file / bounded-fetch 2026-09-19: `38 passed`
- Suite locale dopo fix F23 (snippet centrati sul match) 2026-09-19: `41 passed`
- Suite locale dopo fix F10 (logs_triage) + F16 (argomenti piatti) 2026-09-19: `49 passed`
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
  - F6 chiuso meglio nel passaggio finale: i candidati con `score=0` non dichiarano piu' falso "keyword overlap", ma vengono marcati come fallback espliciti
  - F8 fixato: `candidate_symbols` limitato ai file effettivamente esposti in `candidate_files`
  - F17 chiuso: le scansioni di directory raccolgono ora anche file di configurazione senza suffisso standard come `.env`, `.env.template`, `Dockerfile`, `Makefile`, `Procfile`
  - F18 chiuso: `terminal_commands` vengono ora eseguiti con la stessa policy anche in `codebase_discovery` e `docs_research`; non spariscono piu' in `commands_run`
  - grounding fix aggiuntivo: l'LLM vede ora `candidate_files` + `candidate_symbols` + `small_snippets` + finding meccanici nel prompt, e non puo' piu' sovrascrivere `relevant_findings` con allucinazioni
  - lingua output LLM resa esplicita nel contratto: `DiscoveryRequest.response_language` con default `en`; il prompt usa questa scelta invece di inferirla dall'obiettivo
  - LLM hardening aggiuntivo:
    - `api_key_env` ora puo' essere `null` per endpoint locali keyless
    - `require_api_key` configurabile per profilo/env
    - `supports_json_response_format` configurabile per provider OpenAI-compatible che rifiutano `response_format`
    - `timeout_seconds` per profilo finalmente applicato davvero dal client HTTP
  - F9 migliorato: `small_snippets` non si fermano piu' alla prima occorrenza nel file; ora espongono piu' regioni rilevanti dello stesso file (utile sui file multi-`except`)
  - F9 migliorato ancora: la fusione degli snippet salta solo le finestre interamente coperte (`end <= covered_until`) e il cap per file sale fino a 5 snippet; il caso denso da 5 `except` resta coperto
  - fairness snippet migliorata: il budget globale viene distribuito round-robin tra i top documenti, cosi' un file denso non prosciuga tutta l'evidenza disponibile
  - lingua output LLM irrigidita: il prompt usa `response_language`; default English, override esplicito del caller quando serve
  - README riallineato alla configurazione reale: ora documenta inline i template MCP JSON per Trae/Windows e OpenClaw/Linux, piu' la regola esplicita su chi decide il provider attivo (`HEADROOM_AGENT_MODEL_PROVIDER` vs override `model_profile`)
  - F20 chiuso: i file molto grandi non causano piu' falsi negativi silenziosi senza avviso; se la lettura viene troncata il tool espone una `uncertainties` esplicita
  - F21 chiuso: le letture locali non usano piu' `Path.read_text()[:20000]`; ora leggono in modo bounded solo il preview necessario senza caricare tutto il file in memoria
  - F22 chiuso: anche il fetch diretto di URL e' bounded e la documentazione del tool/README ora dichiara esplicitamente questo limite operativo
  - F23 chiuso: gli snippet non sono piu' tagliati dal solo prefisso del blocco; la finestra e' centrata sulla colonna del match, quindi su sorgenti a riga lunga (JS minificato, JSON su una riga, CSV/log a riga singola) l'evidenza contiene davvero il termine cercato invece di essere muta
  - F23 verificato con 3 regressioni: needle in fondo a riga lunga, JSON minificato su una riga, e caso multi-riga normale che resta invariato (nessun marcatore di ellissi)
  - residui NON affrontati in questo passaggio:
    - analisi istanze multiple lato host (`F12`): dopo `mcp reload` osservata una sola istanza; resta nota operativa, non difetto di codice
    - esercizio automatico del proxy Headroom (`F13`): `HEADROOM_PROXY_URL` non e' impostato nel launcher stdio live, quindi il percorso proxy non e' esercitato in produzione
  - F10 chiuso: in `logs_triage` i path di test/fixture (`tests`, `test`, `__tests__`, `spec`, `specs`) vengono ignorati quando esistono log reali; i findings sono deduplicati e ordinati per severita' (error > warning > info); uno scope esplicito su un singolo file di test resta rispettato
  - F16 chiuso: il tool `run_discovery` accetta ora anche argomenti piatti (`objective`, `objective_type`, `scope_paths`, ...) mantenendo `params` come busta retro-compatibile, cosi' OpenClaw e i client esistenti continuano a funzionare
  - `scripts/run_tests_dgx.sh` ora fa `cd "$ROOT_DIR"` prima di pytest: senza quel `cd` i 4 test smoke con path relativi fallivano a torto
  - suite locale dopo `response_language` esplicito + fairness round-robin snippet: `36 passed`
  - suite locale dopo fix F23 (snippet centrati sulla colonna del match): `41 passed`
  - suite locale dopo fix F10 + F16 (argomenti piatti + logs_triage): `49 passed`

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
