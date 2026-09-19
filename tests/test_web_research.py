import json
from pathlib import Path

import pytest

from headroom_agent_mcp.config import HeadroomAgentConfig
from headroom_agent_mcp.models import (
    CommandAllowlistProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    ObjectiveType,
)
from headroom_agent_mcp.service import DiscoveryService, EvidenceDocument
from headroom_agent_mcp.websearch import (
    SearchResult,
    _decode_duckduckgo_url,
    _DuckDuckGoParser,
    extract_readable_text,
    resolve_search_chain,
    search_web,
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
