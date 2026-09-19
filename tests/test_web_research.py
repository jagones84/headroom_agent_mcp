import json
from pathlib import Path

import httpx
import pytest

from headroom_agent_mcp.cache import TTLCache
from headroom_agent_mcp.config import HeadroomAgentConfig
from headroom_agent_mcp.models import (
    CommandAllowlistProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    ObjectiveType,
)
from headroom_agent_mcp.service import DiscoveryService, EvidenceDocument
from headroom_agent_mcp.websearch import (
    HTTP_MAX_ATTEMPTS,
    SearchResult,
    TransientStatusError,
    _decode_duckduckgo_url,
    _DuckDuckGoParser,
    _request_with_retries,
    _search_tavily,
    bm25_scores,
    canonicalize_url,
    content_fingerprint,
    dedupe_search_results,
    domain_of,
    extract_readable_text,
    fetch_url_readable,
    resolve_search_chain,
    search_web,
    tavily_search_depth,
)

HTML_WITH_BOILERPLATE = (
    "<html><head>"
    "<title>Page</title>"
    "<script>var secret = 1;</script>"
    "<style>.a{color:red}</style>"
    "</head><body>"
    "<nav>menu links</nav>"
    "<article><h1>Real Title</h1><p>The real content lives here.</p></article>"
    "<footer>footer noise</footer>"
    "</body></html>"
)


def test_extract_readable_text_drops_scripts_styles_head_and_chrome() -> None:
    text = extract_readable_text(HTML_WITH_BOILERPLATE)

    assert "The real content lives here." in text
    assert "Real Title" in text
    assert "var secret" not in text
    assert "color:red" not in text
    assert "footer noise" not in text
    assert "menu links" not in text


def test_fetch_url_extracts_readable_text_before_bounding(monkeypatch) -> None:
    monkeypatch.setattr(
        "headroom_agent_mcp.service.fetch_url_readable",
        lambda url: (extract_readable_text(HTML_WITH_BOILERPLATE), False),
    )

    text, truncated = DiscoveryService()._fetch_url("https://example.com/page")

    assert "The real content lives here." in text
    assert "var secret" not in text
    assert truncated is False


def test_web_research_delegates_search_and_keeps_full_evidence_for_the_proxy(monkeypatch) -> None:
    def fake_search(query: str, limit: int, provider: str | None = None):
        return ([SearchResult(title="Doc", url="https://example.com/a", snippet="search snippet")], "tavily")

    monkeypatch.setattr("headroom_agent_mcp.service.search_web", fake_search)
    monkeypatch.setattr(
        "headroom_agent_mcp.service.fetch_url_readable",
        lambda url: ("Extended body knowledge about MCP_ENDPOINT configuration.", False),
    )

    service = DiscoveryService(llm_evidence_char_budget=12000)
    request = DiscoveryRequest(
        objective="Explain MCP_ENDPOINT",
        objective_type=ObjectiveType.WEB_RESEARCH,
        scope_paths=[],
        query_hints=["MCP_ENDPOINT"],
        command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        max_files=3,
        raw_read_budget=3,
    )

    response = service.run(request)

    assert response.summary.startswith("Web research via tavily")
    assert any("example.com" in item.path for item in response.candidate_files)
    evidence = json.loads(service._format_llm_evidence(response))
    assert any("Extended body knowledge" in item.get("text", "") for item in evidence["evidence_items"])


def test_llm_evidence_is_structured_json_for_the_proxy_compressor() -> None:
    service = DiscoveryService(llm_evidence_char_budget=12000)
    service._llm_documents = [
        EvidenceDocument(path=f"https://example.com/{index}", text="Body paragraph.\n\n" * 200, score=1.0)
        for index in range(3)
    ]
    response = DiscoveryResponse(
        summary="s",
        objective_type=ObjectiveType.WEB_RESEARCH,
        relevant_findings=[],
        candidate_files=[],
        candidate_symbols=[],
        small_snippets=[],
        commands_run=[],
        raw_reads_needed_by_parent=[],
        uncertainties=["cross-check"],
        recommended_next_action="",
        confidence="medium",
    )

    payload = json.loads(service._format_llm_evidence(response))

    assert payload["objective_type"] == "web_research"
    assert payload["uncertainties"] == ["cross-check"]
    assert len(payload["evidence_items"]) > 3
    assert payload["evidence_items"][0]["source"] == "https://example.com/0"
    assert {"rank", "section", "score", "text"} <= set(payload["evidence_items"][0])


def test_evidence_sections_split_long_single_line_documents() -> None:
    sections = DiscoveryService._split_evidence_sections("x" * 3000, chunk_chars=1000)

    assert [len(section) for section in sections] == [1000, 1000, 1000]


def test_evidence_sections_keep_short_documents_whole() -> None:
    assert DiscoveryService._split_evidence_sections("short body") == ["short body"]


def test_web_research_reports_missing_provider(monkeypatch) -> None:
    monkeypatch.setattr("headroom_agent_mcp.service.search_web", lambda query, limit, provider=None: ([], None))

    response = DiscoveryService().run(
        DiscoveryRequest(
            objective="Explain MCP_ENDPOINT",
            objective_type=ObjectiveType.WEB_RESEARCH,
            command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        )
    )

    assert any("no web search provider" in item.lower() for item in response.uncertainties)
    assert response.confidence == "low"


def test_config_expands_llm_evidence_budget_when_proxy_is_configured(monkeypatch) -> None:
    monkeypatch.delenv("HEADROOM_AGENT_LLM_EVIDENCE_CHARS", raising=False)
    monkeypatch.delenv("HEADROOM_AGENT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("HEADROOM_PROXY_URL", raising=False)

    direct = HeadroomAgentConfig.from_sources()
    assert direct.llm_evidence_char_budget == 12000
    assert direct.llm_profiles["openrouter"].timeout_seconds == 45

    monkeypatch.setenv("HEADROOM_PROXY_URL", "http://127.0.0.1:8788")
    proxied = HeadroomAgentConfig.from_sources()
    assert proxied.llm_evidence_char_budget == 40000
    assert proxied.llm_profiles["openrouter"].timeout_seconds == 120
    assert proxied.llm_profiles["openrouter"].use_headroom_proxy is True


def test_config_respects_explicit_evidence_budget(monkeypatch) -> None:
    monkeypatch.setenv("HEADROOM_AGENT_LLM_EVIDENCE_CHARS", "40000")

    assert HeadroomAgentConfig.from_sources().llm_evidence_char_budget == 40000


def test_url_text_limit_follows_evidence_budget() -> None:
    service = DiscoveryService(llm_evidence_char_budget=150000)

    assert service.url_text_limit == 150000


def test_url_text_limit_never_drops_below_file_read_limit() -> None:
    service = DiscoveryService(llm_evidence_char_budget=1000)

    assert service.url_text_limit == 20_000


def test_repo_declares_websearch_module() -> None:
    assert (Path("src/headroom_agent_mcp/websearch.py")).is_file()


DDG_HTML = (
    '<div class="result">'
    '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage&amp;rut=abc">'
    "Example Title</a>"
    '<a class="result__snippet">A useful snippet.</a>'
    "</div>"
    '<div class="result">'
    '<a class="result__a" href="https://plain.example/other">Second Result</a>'
    '<div class="result__snippet">Another snippet.</div>'
    "</div>"
)


def _boom(*_args: object, **_kwargs: object) -> list[SearchResult]:
    raise RuntimeError("provider unavailable")


def test_decode_duckduckgo_url_unwraps_redirects_and_passes_plain_links() -> None:
    assert _decode_duckduckgo_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fpage") == "https://example.com/page"
    assert _decode_duckduckgo_url("https://plain.example/x") == "https://plain.example/x"
    assert _decode_duckduckgo_url("") == ""


def test_duckduckgo_parser_extracts_titles_urls_and_snippets() -> None:
    parser = _DuckDuckGoParser()
    parser.feed(DDG_HTML)

    assert [item["title"] for item in parser.results] == ["Example Title", "Second Result"]
    assert parser.results[0]["url"] == "https://example.com/page"
    assert parser.results[1]["url"] == "https://plain.example/other"
    assert "useful snippet" in parser.results[0]["snippet"]
    assert "Another snippet" in parser.results[1]["snippet"]


def test_search_chain_orders_available_providers(monkeypatch) -> None:
    monkeypatch.delenv("HEADROOM_AGENT_SEARCH_PROVIDER", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("BRAVE_API_KEY", "b")

    assert resolve_search_chain() == ["tavily", "brave", "duckduckgo"]
    assert resolve_search_chain("brave") == ["brave", "tavily", "duckduckgo"]


def test_search_chain_keeps_duckduckgo_when_no_keys_are_set(monkeypatch) -> None:
    monkeypatch.delenv("HEADROOM_AGENT_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)

    assert resolve_search_chain() == ["duckduckgo"]
    assert resolve_search_chain("tavily") == ["duckduckgo"]


def test_search_web_falls_back_to_the_next_provider(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("BRAVE_API_KEY", "b")
    monkeypatch.setattr("headroom_agent_mcp.websearch._search_tavily", _boom)
    monkeypatch.setattr(
        "headroom_agent_mcp.websearch._search_brave",
        lambda query, limit, api_key: [SearchResult(title="Brave hit", url="https://b.example", snippet="s")],
    )

    results, provider = search_web("query", 3)

    assert provider == "brave"
    assert results[0].url == "https://b.example"


def test_search_web_uses_keyless_duckduckgo_when_keyed_providers_fail(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr("headroom_agent_mcp.websearch._search_tavily", _boom)
    monkeypatch.setattr(
        "headroom_agent_mcp.websearch._search_duckduckgo",
        lambda query, limit, api_key=None: [SearchResult(title="DDG hit", url="https://d.example", snippet="s")],
    )

    results, provider = search_web("query", 2)

    assert provider == "duckduckgo"
    assert results[0].url == "https://d.example"


def test_search_web_raises_when_every_provider_errors(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr("headroom_agent_mcp.websearch._search_tavily", _boom)
    monkeypatch.setattr("headroom_agent_mcp.websearch._search_duckduckgo", _boom)

    with pytest.raises(RuntimeError):
        search_web("query", 2)


def test_domain_of_strips_www_case_and_port() -> None:
    assert domain_of("HTTPS://WWW.Example.COM:8443/path") == "example.com"
    assert domain_of("https://docs.python.org/3/") == "docs.python.org"


def test_canonicalize_url_ignores_fragment_tracking_and_scheme() -> None:
    noisy = canonicalize_url("https://www.Example.com/Page/?utm_source=news&id=7#section")
    clean = canonicalize_url("http://example.com/Page?id=7")

    assert noisy == clean == "example.com/Page?id=7"
    assert canonicalize_url("") == ""


def test_dedupe_search_results_drops_duplicate_urls() -> None:
    results = [
        SearchResult(title="A", url="https://example.com/a", snippet=""),
        SearchResult(title="A mirror", url="https://www.example.com/a/#top", snippet=""),
        SearchResult(title="B", url="https://other.example/b", snippet=""),
    ]

    kept = dedupe_search_results(results)

    assert [item.title for item in kept] == ["A", "B"]


def test_dedupe_search_results_caps_results_per_domain() -> None:
    results = [
        SearchResult(title=f"p{index}", url=f"https://github.com/repo/{index}", snippet="")
        for index in range(4)
    ]
    results.append(SearchResult(title="docs", url="https://docs.python.org/3/", snippet=""))

    capped = dedupe_search_results(results, max_per_domain=2)

    assert [item.title for item in capped] == ["p0", "p1", "docs"]
    assert len(dedupe_search_results(results, max_per_domain=0)) == 5


def test_content_fingerprint_normalizes_case_and_whitespace() -> None:
    assert content_fingerprint("Hello   World\n\nAgain") == content_fingerprint("hello world again")


def test_bm25_scores_rank_the_page_matching_the_query_first() -> None:
    documents = [
        "unrelated page about gardening and weather",
        "context compression for llm agents reduces token usage",
        "a page mentioning compression once",
    ]

    scores = bm25_scores(documents, "context compression llm agents")

    assert scores[0] == 0.0
    assert scores[1] > scores[2] > 0.0


def test_bm25_scores_length_normalize_so_padding_does_not_win() -> None:
    padded = "compression " + " ".join(f"filler{index}" for index in range(200))

    scores = bm25_scores(["compression", padded], "compression")

    assert scores[0] > scores[1]


def test_bm25_scores_return_zeros_without_a_query() -> None:
    assert bm25_scores(["a b c"], "") == [0.0]
    assert bm25_scores([], "query") == []


def test_web_research_dedupes_reranks_and_declares_dropped_results(monkeypatch) -> None:
    results = [
        SearchResult(title="Mirror one", url="https://mirror.example/a", snippet="s1"),
        SearchResult(title="Mirror two", url="https://www.mirror.example/a/", snippet="s2"),
        SearchResult(title="Deep dive", url="https://deep.example/page", snippet="s3"),
        SearchResult(title="Filler", url="https://filler.example/x", snippet="s4"),
    ]
    monkeypatch.setattr(
        "headroom_agent_mcp.service.search_web",
        lambda query, limit, provider=None: (results, "brave"),
    )
    bodies = {
        "https://mirror.example/a": "totally unrelated gardening notes",
        "https://deep.example/page": "context compression for llm agents reduces token usage substantially",
        "https://filler.example/x": "a short note that mentions compression once",
    }
    monkeypatch.setattr(
        "headroom_agent_mcp.service.fetch_url_readable",
        lambda url: (bodies[url], False),
    )

    response = DiscoveryService(llm_evidence_char_budget=12000).run(
        DiscoveryRequest(
            objective="context compression for llm agents",
            objective_type=ObjectiveType.WEB_RESEARCH,
            command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
            max_files=5,
        )
    )

    assert [item.path for item in response.candidate_files] == [
        "https://deep.example/page",
        "https://filler.example/x",
        "https://mirror.example/a",
    ]
    assert any("duplicate search result" in item for item in response.uncertainties)


def test_web_research_skips_pages_that_repeat_earlier_text(monkeypatch) -> None:
    results = [
        SearchResult(title="First", url="https://one.example/a", snippet=""),
        SearchResult(title="Syndicated copy", url="https://two.example/b", snippet=""),
    ]
    shared = "Context compression for llm agents. " * 20
    monkeypatch.setattr(
        "headroom_agent_mcp.service.search_web",
        lambda query, limit, provider=None: (results, "brave"),
    )
    monkeypatch.setattr(
        "headroom_agent_mcp.service.fetch_url_readable",
        lambda url: (shared, False),
    )

    response = DiscoveryService(llm_evidence_char_budget=12000).run(
        DiscoveryRequest(
            objective="context compression for llm agents",
            objective_type=ObjectiveType.WEB_RESEARCH,
            command_allowlist_profile=CommandAllowlistProfile.SAFE_READONLY,
        )
    )

    assert [item.path for item in response.candidate_files] == ["https://one.example/a"]
    assert any("duplicated an earlier source" in item for item in response.uncertainties)


def _response(status: int, *, retry_after: str | None = None, payload: dict | None = None) -> httpx.Response:
    headers = {"retry-after": retry_after} if retry_after is not None else {}
    return httpx.Response(
        status,
        headers=headers,
        json=payload or {},
        request=httpx.Request("GET", "https://example.com"),
    )


def test_request_with_retries_retries_a_retryable_status(monkeypatch) -> None:
    queue = [_response(429, retry_after="0"), _response(200, payload={"ok": True})]
    slept: list[float] = []
    monkeypatch.setattr(
        "headroom_agent_mcp.websearch.httpx.request", lambda method, url, **kwargs: queue.pop(0)
    )

    response = _request_with_retries("GET", "https://example.com", sleep=slept.append)

    assert response.status_code == 200
    assert slept == [0.0]


def test_request_with_retries_uses_backoff_when_retry_after_is_absent(monkeypatch) -> None:
    queue = [_response(503), _response(200)]
    slept: list[float] = []
    monkeypatch.setattr(
        "headroom_agent_mcp.websearch.httpx.request", lambda method, url, **kwargs: queue.pop(0)
    )

    _request_with_retries("GET", "https://example.com", sleep=slept.append)

    assert len(slept) == 1
    assert slept[0] > 0


def test_request_with_retries_raises_after_the_attempt_budget(monkeypatch) -> None:
    attempts: list[int] = []
    monkeypatch.setattr(
        "headroom_agent_mcp.websearch.httpx.request",
        lambda method, url, **kwargs: (attempts.append(1), _response(429))[1],
    )

    with pytest.raises(TransientStatusError):
        _request_with_retries("GET", "https://example.com", sleep=lambda _seconds: None)

    assert len(attempts) == HTTP_MAX_ATTEMPTS


def test_request_with_retries_does_not_retry_a_client_error(monkeypatch) -> None:
    attempts: list[int] = []
    monkeypatch.setattr(
        "headroom_agent_mcp.websearch.httpx.request",
        lambda method, url, **kwargs: (attempts.append(1), _response(404))[1],
    )

    response = _request_with_retries("GET", "https://example.com", sleep=lambda _s: None)

    assert response.status_code == 404
    assert len(attempts) == 1


def test_request_with_retries_retries_a_transport_error(monkeypatch) -> None:
    attempts: list[int] = []

    def flaky(method, url, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise httpx.ConnectError("connection reset")
        return _response(200)

    monkeypatch.setattr("headroom_agent_mcp.websearch.httpx.request", flaky)

    response = _request_with_retries("GET", "https://example.com", sleep=lambda _s: None)

    assert response.status_code == 200
    assert len(attempts) == 2


def test_tavily_search_depth_defaults_to_advanced_and_rejects_junk(monkeypatch) -> None:
    monkeypatch.delenv("HEADROOM_AGENT_TAVILY_SEARCH_DEPTH", raising=False)
    assert tavily_search_depth() == "advanced"

    monkeypatch.setenv("HEADROOM_AGENT_TAVILY_SEARCH_DEPTH", "BASIC")
    assert tavily_search_depth() == "basic"

    monkeypatch.setenv("HEADROOM_AGENT_TAVILY_SEARCH_DEPTH", "turbo")
    assert tavily_search_depth() == "advanced"


def test_search_tavily_sends_the_configured_depth(monkeypatch) -> None:
    captured: dict[str, dict] = {}

    def fake_request(method, url, **kwargs):
        captured["json"] = kwargs["json"]
        return _response(200, payload={"results": []})

    monkeypatch.setattr("headroom_agent_mcp.websearch._request_with_retries", fake_request)
    monkeypatch.delenv("HEADROOM_AGENT_TAVILY_SEARCH_DEPTH", raising=False)

    _search_tavily("query", 3, "key")
    assert captured["json"]["search_depth"] == "advanced"
    assert captured["json"]["max_results"] == 3


def test_search_web_caches_successful_results(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setattr("headroom_agent_mcp.websearch._CACHE", TTLCache(tmp_path, ttl_seconds=60))
    calls: list[str] = []

    def fake_tavily(query, limit, api_key):
        calls.append(query)
        return [SearchResult(title="Hit", url="https://example.com/a", snippet="s")]

    monkeypatch.setattr("headroom_agent_mcp.websearch._search_tavily", fake_tavily)

    first = search_web("Context Compression", 5)
    second = search_web("context compression", 5)

    assert len(calls) == 1
    assert [item.url for item in second[0]] == ["https://example.com/a"]
    assert second[1] == "tavily"
    assert first[1] == second[1]


def test_search_web_does_not_cache_failures(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.delenv("BRAVE_API_KEY", raising=False)
    monkeypatch.setattr("headroom_agent_mcp.websearch._CACHE", TTLCache(tmp_path, ttl_seconds=60))
    attempts: list[int] = []

    def failing(query, limit, api_key=None):
        attempts.append(1)
        raise RuntimeError("provider down")

    monkeypatch.setattr("headroom_agent_mcp.websearch._search_tavily", failing)
    monkeypatch.setattr("headroom_agent_mcp.websearch._search_duckduckgo", failing)

    for _ in range(2):
        with pytest.raises(RuntimeError):
            search_web("query", 2)

    assert len(attempts) == 4


def test_fetch_url_readable_caches_by_canonical_url(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("headroom_agent_mcp.websearch._CACHE", TTLCache(tmp_path, ttl_seconds=60))
    fetched: list[str] = []

    def fake_stream(url):
        fetched.append(url)
        return ("<html><body><p>Hello cached page</p></body></html>", "text/html", False)

    monkeypatch.setattr("headroom_agent_mcp.websearch._stream_readable", fake_stream)

    first = fetch_url_readable("https://www.example.com/page/?utm_source=news")
    second = fetch_url_readable("http://example.com/page")

    assert first == second
    assert "Hello cached page" in first[0]
    assert len(fetched) == 1


def test_fetch_url_readable_does_not_cache_failures(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("headroom_agent_mcp.websearch._CACHE", TTLCache(tmp_path, ttl_seconds=60))
    attempts: list[int] = []

    def failing(url):
        attempts.append(1)
        raise httpx.ConnectError("connection reset by peer")

    monkeypatch.setattr("headroom_agent_mcp.websearch._stream_readable", failing)
    monkeypatch.setattr("headroom_agent_mcp.websearch.time.sleep", lambda _seconds: None)

    assert fetch_url_readable("https://example.com/x") == ("", False)
    assert fetch_url_readable("https://example.com/x") == ("", False)
    assert len(attempts) == 2 * HTTP_MAX_ATTEMPTS


def test_fetch_many_preserves_input_order() -> None:
    service = DiscoveryService(llm_evidence_char_budget=12000)
    seen: list[str] = []

    def fake_fetch(url: str) -> tuple[str, bool]:
        seen.append(url)
        return f"body of {url}", False

    service._fetch_url = fake_fetch  # type: ignore[method-assign]

    urls = [f"https://example.com/{index}" for index in range(5)]
    results = service._fetch_many(urls)

    assert [text for text, _ in results] == [f"body of {url}" for url in urls]
    assert sorted(seen) == sorted(urls)


def test_fetch_many_handles_the_single_url_case() -> None:
    service = DiscoveryService(llm_evidence_char_budget=12000)
    service._fetch_url = lambda url: (f"only {url}", True)  # type: ignore[method-assign]

    assert service._fetch_many(["https://example.com/one"]) == [("only https://example.com/one", True)]
    assert service._fetch_many([]) == []
