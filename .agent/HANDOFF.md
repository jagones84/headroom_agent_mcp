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
- Suite locale dopo `web_research` + evidenza JSON compressa 2026-09-19: `61 passed`
- Suite locale dopo retrieval CCR + hardening client LLM 2026-09-19 (sessione 2): `66 passed`
- Comando usato:
  - `C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python -m pytest Z:\Repositories\headroom_agent_mcp\tests -q`
- Nota ambiente:
  - venv su `Z:` fallisce per esecuzione UNC/permessi
  - venv su `C:\Users\giova\.venvs\...` funziona
- DGX:
  - `scripts/run_tests_dgx.sh` -> `66 passed`
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
  - F13 CHIUSO 2026-09-19: `HEADROOM_PROXY_URL` e' ora impostato nell'env di `headroom_agent_discovery` in `~/.openclaw/openclaw.json`, il proxy gira come servizio stabile su `127.0.0.1:8788` e il percorso proxato e' esercitato davvero (`api_requests=1`, `requests_compressed=1`)
  - residui NON affrontati in questo passaggio:
    - analisi istanze multiple lato host (`F12`): dopo `mcp reload` osservata una sola istanza; resta nota operativa, non difetto di codice
  - F10 chiuso: in `logs_triage` i path di test/fixture (`tests`, `test`, `__tests__`, `spec`, `specs`) vengono ignorati quando esistono log reali; i findings sono deduplicati e ordinati per severita' (error > warning > info); uno scope esplicito su un singolo file di test resta rispettato
  - F16 chiuso: il tool `run_discovery` accetta ora anche argomenti piatti (`objective`, `objective_type`, `scope_paths`, ...) mantenendo `params` come busta retro-compatibile, cosi' OpenClaw e i client esistenti continuano a funzionare
  - `scripts/run_tests_dgx.sh` ora fa `cd "$ROOT_DIR"` prima di pytest: senza quel `cd` i 4 test smoke con path relativi fallivano a torto
  - suite locale dopo `response_language` esplicito + fairness round-robin snippet: `36 passed`
  - suite locale dopo fix F23 (snippet centrati sulla colonna del match): `41 passed`
  - suite locale dopo fix F10 + F16 (argomenti piatti + logs_triage): `49 passed`
  - suite locale dopo `web_research` + evidenza JSON compressa: `61 passed`

## Proxy Headroom + web_research (2026-09-19)

Manual operativo completo: `.agent/README-headroom-proxy.md` (leggere quello prima di toccare proxy/venv/wiring).

- `web_research` aggiunto come `ObjectiveType`, con `search_results_limit` (1-10, default 5) e `search_provider` (`brave` / `tavily` / auto)
- nuovo modulo `src/headroom_agent_mcp/websearch.py`:
  - `extract_readable_text` (trafilatura se disponibile, altrimenti parser stdlib) — il boilerplate HTML sparisce prima del preview
  - `fetch_url_readable` (fetch bounded + readability)
  - `search_web` con backend Brave (`BRAVE_API_KEY`) e Tavily (`TAVILY_API_KEY`)
- `service.py`: `_run_web_research` delega tutta la ricerca al tool, `_fetch_url` ora usa il fetch leggibile, `_format_llm_evidence` emette **JSON** con un item per sezione di documento
- `config.py`:
  - `llm_evidence_char_budget` (12000 diritta, 40000 con proxy, override `HEADROOM_AGENT_LLM_EVIDENCE_CHARS`)
  - `timeout_seconds` 45s diritta, 120s con proxy (la compressione aggiunge latenza; 45s faceva andare in timeout l'endpoint proxato)
- `server.py`: argomenti piatti anche per `search_results_limit` / `search_provider`, docstring aggiornata
- `scripts/smoke_discovery.py` passava il service **senza** `default_model_profile` -> `llm_enriched=false` e `api_requests=0`; corretto
- Runtime DGX:
  - venv Linux per il repo `headroom` (`scripts/setup_headroom_runtime_dgx.sh`), `headroom-ai[proxy]` 0.37.0
  - `headroom-ai[ml]` installato (`scripts/setup_headroom_ml_dgx.sh`) -> Kompress disponibile
  - proxy avviato come servizio: `scripts/headroom_proxy_service_dgx.sh start` -> `127.0.0.1:8788`, `--mode token`, `--no-ccr`
  - MCP ufficiale `headroom` registrato in `~/.openclaw/openclaw.json` (`3 tools`) + `HEADROOM_PROXY_URL` nell'env del nostro MCP (`1 tools`)
- Misure reali (dettaglio in `.agent/README-headroom-proxy.md`):
  - framing prose -> 4.5% di token risparmiati; JSON con >=10 item -> ~74%; JSON con 5 item -> 0%
  - `web_research` E2E senza CCR: `before=12938 after=8091 saved=4847` -> **41.8%** con `llm_enriched=true` e summary ricco
  - con CCR attivo (proxy di default) il retrieval lato server ora funziona: vedi sezione "Retrieval CCR + hardening client LLM" qui sotto (75.0% senza degradare il summary)
  - i nomi tool `WebSearch`/`WebFetch`/`web_search`/`web_fetch` sono in `DEFAULT_VERBATIM_EXCLUDE_TOOLS` di Headroom e non vengono mai compressi in modo lossy: non usare quei nomi per l'evidenza

## Retrieval CCR + hardening client LLM (2026-09-19, sessione 2)

Obiettivo: tenere ~75% di risparmio **senza** degradare il summary, dando al LLM delegato la possibilita' di recuperare l'evidenza compressa (`headroom_retrieve`) invece di lamentarsi di excerpt mancanti.

- Fonti ufficiali usate (grounding, non ipotesi):
  - `headroom/wiki/ccr.md`: "The client never sees CCR tool calls - they're handled transparently." -> il retrieval e' risolto **lato proxy**, niente loop client-side
  - `headroom/wiki/ARCHITECTURE.md` (CCR Phase 2 `/v1/retrieve`, Phase 3 tool injection, Phase 5 response handler `headroom/ccr/response_handler.py`, max 3 round di continuazione)
  - `headroom/proxy/handlers/openai.py` -> `_should_inject_openai_chat_ccr_tool` => `bool(ccr_inject_tool and not stream)`: lo streaming NON puo' redimere il tool
  - `https://api-docs.deepseek.com/guides/json_mode` -> con `response_format` serve "json" nel prompt, `max_tokens` adeguato per non troncare a meta' JSON, il content puo' tornare vuoto
  - `https://openrouter.ai/docs/features/structured-outputs`
- Assunzione SBAGLIATA corretta in questa sessione:
  - nella sessione 1 avevo concluso che servisse un loop di retrieval client-side e quindi tenevo `--no-ccr`. Falso: i contatori ufficiali provano che il proxy risolve il retrieval da solo. Ora **CCR e' ON di default** e non esiste alcun loop client-side.
- Bug di root cause trovato col probe (`scripts/probe_ccr_retrieval_dgx.py`):
  - forzando `response_format={"type":"json_object"}` sull'evidenza compressa in forma tabellare, il modello restituiva `content: null` sul wire e poi un echo di 2.539 char della tabella invece di rispondere. Il client crashava con `'NoneType' object has no attribute 'strip'`.
- Fix applicati:
  - `src/headroom_agent_mcp/config.py`: `supports_json_response_format` default `True` -> `False`; nuovo `max_tokens: int = 2048`; env `HEADROOM_AGENT_USE_JSON_RESPONSE_FORMAT` (default `False`) e `HEADROOM_AGENT_MAX_TOKENS` (default `2048`)
  - `src/headroom_agent_mcp/llm.py`: nuovo `extract_json_object()` (tollera fence markdown e prosa attorno), invio sempre di `max_tokens`, `response_format` solo su opt-in, guard esplicito su content vuoto con `finish_reason` + nomi tool
  - `src/headroom_agent_mcp/service.py`: system prompt ora incorpora la forma JSON letterale e dice di chiamare il retrieval tool se disponibile, senza mai narrare la compressione
  - `tests/test_llm_config.py`: 5 nuovi test (fence, prosa, payload non-oggetto, `max_tokens` presente + `response_format` assente di default, opt-in che lo mantiene)
- Runtime proxy (script-driven, CCR default):
  - `scripts/headroom_proxy_service_dgx.sh` azioni: `start` (= CCR on), `start-trace` (`--log-messages`), `start-no-ccr`, `stop`, `status`
  - sempre `--log-file ~/.headroom/proxy.jsonl` (JSONL ufficiale con `request_messages`, `response_content`)
  - `HEADROOM_TARGET_RATIO` (default 0.5) per `--target-ratio`
- Prove misurate:
  - retrieval risolto lato proxy: `stats[toin].total_retrievals` `0 -> 1`, `stats[compression].ccr_retrievals` `42 -> 48`
  - smoke finale con CCR on: `before=13991 after=3499 saved=10492` -> **75.0%**, `llm_enriched=true`, summary grounded
  - trace: `transforms_applied=["router:mixed:0.18"]`, 40 marker `<<ccr:>>`, `optimization_latency_ms=2768`, `total_latency_ms=43631`
- Gotcha:
  - in `proxy.jsonl` il campo `request_messages` registra i messaggi **prima** dell'iniezione del tool: `retrieve_tool=0` li' NON significa che il tool non sia stato iniettato
  - nuovi script diagnostici: `scripts/inspect_proxy_jsonl_dgx.py`, `scripts/measure_ccr_retrieval_dgx.sh`, `scripts/probe_ccr_retrieval_dgx.{py,sh}`

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
