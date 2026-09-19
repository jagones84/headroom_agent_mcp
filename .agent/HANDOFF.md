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
- Suite locale dopo catena fallback websearch 2026-09-19 (sessione 3): `73 passed`
- Suite locale dopo retry CCR metadata-only 2026-09-19 (sessione 4): `78 passed`
- Suite locale dopo dedup + rerank BM25 websearch 2026-09-19 (sessione 5): `88 passed`
- Suite locale dopo cache TTL + retry + fetch concorrente 2026-09-19 (sessione 6): `109 passed`
- Comando usato:
  - `C:\Users\giova\.venvs\headroom_agent_mcp\Scripts\python -m pytest Z:\Repositories\headroom_agent_mcp\tests -q`
- Nota ambiente:
  - venv su `Z:` fallisce per esecuzione UNC/permessi
  - venv su `C:\Users\giova\.venvs\...` funziona
- DGX:
  - `scripts/run_tests_dgx.sh` -> `109 passed`
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

## Web search fallback chain (2026-09-19, sessione 3)

- Prima `websearch.py` sceglieva UN provider con priorita' secca (tavily > brave) e **non aveva alcun fallback**: se quello scelto falliva, risultato vuoto + incertezza.
- Ora c'e' una catena: `resolve_search_chain()` -> `tavily` -> `brave` -> `duckduckgo`; `search_web()` prova in ordine e vince il primo che ritorna risultati.
- DuckDuckGo e' **keyless**: fallback sempre disponibile. Parsa l'endpoint no-JS `html.duckduckgo.com` con un `HTMLParser` stdlib (`_DuckDuckGoParser` + `_decode_duckduckgo_url` per de-rimbalzare i link `uddg=`). Nessuna dipendenza nuova.
- `search_provider` esplicito ora **ordina** la catena (mette quel provider per primo) invece di sceglierne uno solo; `HEADROOM_AGENT_SEARCH_PROVIDER` fa lo stesso da env.
- Se TUTTI i provider vanno in errore -> `search_web` solleva e `service.py` riporta "Web search failed"; se uno ritorna vuoto -> incertezza con il provider provato.
- Verifica: 7 test nuovi (catena, fallback, parser DDG, decode URL) -> suite locale `73 passed`.
- Verifica LIVE sul DGX (venv `headroom_agent_mcp`): `search_web("headroom context compression", 5, "duckduckgo")` -> `provider_used=duckduckgo results=5`, titoli reali e URL de-rimbalzati. Da Windows la stessa chiamata viene resettata (`WinError 10054`) -> blocco anti-bot/host-local, non un bug del codice; il MCP gira sul DGX dove funziona.

## Cap 3 round CCR + retry metadata-only (2026-09-19, sessione 4)

- Report §5.16 confermato sul campo 2/2 + le mie run: con CCR on il modello (deepseek-v4-flash) chiede ~8-10 `headroom_retrieve` e il proxy, oltre `ccr_max_retrieval_rounds = 3` (`headroom/proxy/models.py:208`), restituisce i tool_calls aperti al client -> `finish_reason='tool_calls'`, content vuoto -> `llm_enriched=false`, fallback meccanico. Compressione OK (71-75%), risposta KO.
- Risposta alla domanda "il cap si alza?": **no, con mezzi supportati**. Verificato in `headroom/proxy/models.py`, `headroom/cli/proxy.py`, `headroom/settings_store.py`: NESSUN flag CLI, env var o chiave settings per `ccr_max_retrieval_rounds`. Le uniche opzioni ufficiali per client che non redimono sono `--no-ccr`, `--lossless`, `--ccr-inline-resolve` (quest'ultimo solo response-path, altro problema). Alzare il cap = patchare il sorgente headroom nel venv = drift. Scartato.
- Fix client (nostro codice, zero patch upstream):
  - `llm.py`: `UnresolvedCCRRetrievalError` (con `tool_names`) sollevato SOLO quando `finish_reason == "tool_calls"` e TUTTE le call pendenti sono `headroom_retrieve`; altri casi restano `RuntimeError` generico.
  - `service.py`: `_maybe_enrich_with_llm` al primo errore CCR ritenta UNA volta con evidenza metadata-only (`max_documents=0`, budget dimezzato); `_format_llm_evidence` accetta `evidence_char_budget` + `max_documents`; prompt ammorbidito (retrieval solo per un singolo fatto bloccante, max 1-2 blocchi).
  - Perche' metadata-only funziona: i marker `<<ccr:>>` nascono dalle sezioni documento, e il proxy inietta `headroom_retrieve` SOLO se `scan_for_markers` trova contenuto compresso (`headroom/ccr/tool_injection.py`). Senza sezioni -> niente marker -> niente tool -> il modello risponde dal presente.
  - Tentativi intermedi scartati dai dati live: retry con budget dimezzato ma top-2 docs -> ancora 3 call aperte (2 run). I marker scalano col NUMERO di item, non solo coi char.
- Prova LIVE decisiva (`scripts/smoke_web_research_dgx.sh`, proxy CCR on): primo tentativo 10 call aperte -> `retrying once with metadata-only evidence` -> `LLM enrichment keys=['confidence', 'recommended_next_action', 'summary'] summary_chars=1187`; report JSON: `llm_enriched: True`, `llm_error: None`, summary grounded ("Based on 5 web sources..."). La request retry (`before=1654 after=1447`) e' piccola e quasi non compressa: giusto, e' gia' magra.
- Test: 5 nuovi (errore tipizzato, caso non-CCR, retry-con-successo, retry-doppio-fail onesto, `max_documents`) -> suite `78 passed` (Windows + DGX).

## Dedup + rerank BM25 della websearch (2026-09-19, sessione 5)

- Lacuna chiusa: con 5 risultati il provider poteva restituire piu' pagine dello stesso sito o lo stesso URL due volte, e il ranking era un semplice conteggio di keyword (premiava le pagine lunghe, non sapeva distinguere un termine discriminativo da uno comune).
- Fonti usate (grounding, non memoria):
  - Robertson & Zaragoza, "The Probabilistic Relevance Framework: BM25 and Beyond" (2009), <https://doi.org/10.1561/1500000019>
  - Apache Lucene `BM25Similarity` (stesse forme, stessi default k1=1.5 / b=0.75), <https://lucene.apache.org/core/9_0_0/core/org/apache/lucene/search/similarities/BM25Similarity.html>
  - URL Standard (il fragment non arriva al server), <https://url.spec.whatwg.org/#concept-url-fragment> + RFC 3986 §6.2.2 (normalizzazione sintattica)
  - implementazione di riferimento letta in `headroom/headroom/relevance/bm25.py` (IDF floorato variante Lucene)
- Nuove funzioni pure in `src/headroom_agent_mcp/websearch.py`:
  - `domain_of()` / `canonicalize_url()`: chiave di confronto che ignora schema, fragment e parametri di tracking (`utm_*`, `fbclid`, ...). Cosi' `http://www.example.com/a/?utm_source=x#top` e `https://example.com/a` collassano.
  - `dedupe_search_results(results, max_per_domain=2)`: droppa URL duplicati e limita i risultati per dominio, preservando l'ordine del provider.
  - `content_fingerprint(text)`: chiave cheap sui primi 400 char normalizzati (case + whitespace) per scoprire mirror/sindacazioni.
  - `bm25_scores(documents, query)`: Okapi BM25 a dipendenze zero (token `[a-z0-9_]+`, IDF floato, saturazione `k1`, normalizzazione `b`).
- `service.py::_run_web_research` ora: dedup PRIMA dei fetch -> fetch -> dedup sul contenuto -> rerank BM25 sul testo `titolo + body` -> sort. `_score_text`/`_search_terms` restano invariati per codebase/logs/docs.
- Trasparenza: i drop finiscono in `uncertainties` ("Dropped N duplicate search result(s)...", "Skipped N page(s) whose readable text duplicated an earlier source."), coerente con la politica F20/F22 "dichiara, non nascondere".
- Test: 10 nuovi (domain_of, canonicalize, dedup URL, cap per dominio, fingerprint, BM25 ranking, BM25 length-normalization, BM25 query vuota, rerank+drop a livello servizio, skip contenuto duplicato) -> suite `88 passed` (Windows + DGX).
- Verifica LIVE (`smoke_web_research_dgx.sh`, proxy CCR on): 5 fonti su 5 **domini distinti** (mem0.ai, langchain.com, zenml.io, zylos.ai, preprints.org), score BM25 decrescenti 4.60 / 4.29 / 4.07 / 2.95 / 2.37, `llm_enriched=true`, summary grounded. Nessun drop in questa run (uncertainties solo col cross-check generico).

## Cache TTL + retry + fetch concorrente (2026-09-19, sessione 6)

- Nuovo modulo `src/headroom_agent_mcp/cache.py`: `TTLCache`, cache su disco **fail-open** (una directory, un file JSON per chiave, `{"key","expires_at","value"}`; la chiave e' salvata nel file cosi' una collisione di hash non puo' restituire il valore di un'altra lookup). TTL 0 disabilita tutto. Scritture atomiche (`os.replace`). Ogni errore I/O = cache miss, mai eccezione: una run non deve dipendere dalla cache.
- `websearch.py`:
  - `get_cache()`/`reset_cache()`: singleton costruito dall'env al primo uso (`HEADROOM_AGENT_CACHE_DIR`, `HEADROOM_AGENT_CACHE_TTL_SECONDS`).
  - `search_web()` cachea SOLO i successi non vuoti (chiave `search::{provider}::{limit}::{query lowercase}`); i fallimenti NON vengono cachati, cosi' un retry arriva davvero alla rete.
  - `fetch_url_readable()` cachea per URL canonico (quindi `?utm_*#top` e `http/https` collassano).
  - `_request_with_retries()`: 3 tentativi con backoff lineare, retry su `429/500/502/503/504` **e** su errori di trasporto, `Retry-After` rispettato e **cappato** (`RETRY_AFTER_MAX_SECONDS=5`) perche' un header ostile non deve bloccare il tool. Sorgenti: RFC 9110 §10.2.3 + Google API design guide (retry di errori transitori).
  - `_stream_readable_with_retries()`: stesso treatment sul fetch, mantenendo la lettura a chunk (il cap di memoria non e' negoziabile). Un `404` NON viene ritentato. Se ogni tentativo fallisce si torna `("", False)` -> il chiamante ricade sullo snippet.
  - `tavily_search_depth()`: `advanced` di default (piu' recall, piu' crediti), override `HEADROOM_AGENT_TAVILY_SEARCH_DEPTH=basic`; valori ignoti -> default. Sorgente: docs Tavily `/search`.
- `service.py`: `_fetch_many()` con `ThreadPoolExecutor` (max 5, `FETCH_CONCURRENCY`). `pool.map` preserva l'ordine di input, quindi il ranking del provider resta il tie-breaker prima del rerank BM25. Con 0/1 URL il pool non viene creato.
- Test: `tests/test_cache.py` (8) + 13 nuovi in `test_web_research.py` (retry su status/trasporto/budget/404-non-ritentato/Retry-After, depth Tavily, cache search hit+no-cache-sui-fallimenti, cache fetch per URL canonico, no-cache-fetch-fallito, ordine di `_fetch_many`, caso singolo/vuoto) + `tests/conftest.py` autouse che disabilita la cache su disco e resetta il singleton (nessun test scrive in `~/.headroom`).
- Prova LIVE (`scripts/measure_websearch_dgx.sh`, nuovo): `search cold=4.82s -> warm=0.00s`; `fetch seq=1.71s -> concurrent=0.36s (4.7x) -> cached=0.05s`, con **testo identico** su tutti e tre i percorsi (`same_content=True`).
- Smoke E2E via proxy CCR dopo le modifiche: retry metadata-only ancora attivo, `summary_chars=1274`, main request `before=13595 after=3652` (73%), `llm_enriched=true`, 5 domini distinti con BM25 7.13 / 4.57 / 4.20 / 2.34 / 1.62.
- `.env.template` aggiornato: `HEADROOM_AGENT_USE_JSON_RESPONSE_FORMAT=false` (era rimasto `true`, incoerente col default reale), `HEADROOM_AGENT_MAX_TOKENS`, `HEADROOM_AGENT_SEARCH_PROVIDER`, `HEADROOM_AGENT_TAVILY_SEARCH_DEPTH`, `HEADROOM_AGENT_CACHE_DIR`, `HEADROOM_AGENT_CACHE_TTL_SECONDS`, `BRAVE_API_KEY`, `TAVILY_API_KEY`.

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
