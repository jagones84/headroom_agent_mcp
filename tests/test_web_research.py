import json
from pathlib import Path

from headroom_agent_mcp.config import HeadroomAgentConfig
from headroom_agent_mcp.models import (
    CommandAllowlistProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    ObjectiveType,
)
from headroom_agent_mcp.service import DiscoveryService, EvidenceDocument
from headroom_agent_mcp.websearch import SearchResult, extract_readable_text

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
