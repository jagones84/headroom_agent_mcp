"""Web search and readable-content extraction helpers for the discovery subagent."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import httpx

SEARCH_TIMEOUT_SECONDS = 20.0
FETCH_TIMEOUT_SECONDS = 20.0
FETCH_MAX_CHARS = 2_000_000
USER_AGENT = "headroom-agent-discovery/0.1 (+https://github.com/jagones84/headroom_agent_mcp)"

SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "svg",
    "head",
    "nav",
    "footer",
    "form",
    "iframe",
    "template",
    "aside",
}
BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "main",
    "li",
    "ul",
    "ol",
    "br",
    "tr",
    "td",
    "th",
    "pre",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
}


@dataclass
class SearchResult:
    """One web search hit."""

    title: str
    url: str
    snippet: str


class _ReadableTextParser(HTMLParser):
    """Dependency-free fallback extractor that keeps visible block text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered in SKIP_TAGS:
            self._skip_depth += 1
        elif lowered in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif lowered in BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._parts.append(data)

    def text(self) -> str:
        """Return normalized visible text."""
        raw = "".join(self._parts)
        raw = re.sub(r"[ \t\f\v]+", " ", raw)
        raw = re.sub(r"\n\s*\n\s*", "\n\n", raw)
        return raw.strip()


def extract_readable_text(html: str) -> str:
    """Extract main readable text, preferring trafilatura when it is installed."""
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(html)
        if extracted and extracted.strip():
            return extracted.strip()
    except Exception:
        pass
    parser = _ReadableTextParser()
    parser.feed(html)
    return parser.text()


def _looks_like_html(payload: str, content_type: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = payload[:2000].lower()
    return "<html" in head or "<!doctype html" in head or "<body" in head


def fetch_url_readable(url: str) -> tuple[str, bool]:
    """Fetch a URL and return its readable text plus a truncation flag.

    The byte cap protects memory; readability extraction happens before any
    preview limit so HTML `<head>` boilerplate never becomes the evidence.
    """
    try:
        with httpx.stream(
            "GET",
            url,
            timeout=FETCH_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            parts: list[str] = []
            chars_read = 0
            truncated = False
            for chunk in response.iter_text():
                if not chunk:
                    continue
                remaining = FETCH_MAX_CHARS - chars_read
                if remaining <= 0:
                    truncated = True
                    break
                if len(chunk) > remaining:
                    parts.append(chunk[:remaining])
                    chars_read += remaining
                    truncated = True
                    break
                parts.append(chunk)
                chars_read += len(chunk)
            raw = "".join(parts)
    except httpx.HTTPError:
        return "", False

    if _looks_like_html(raw, content_type):
        return extract_readable_text(raw), truncated
    return raw, truncated


def _search_tavily(query: str, limit: int, api_key: str) -> list[SearchResult]:
    response = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": limit, "search_depth": "basic"},
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    results: list[SearchResult] = []
    for item in payload.get("results", []):
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        results.append(
            SearchResult(
                title=str(item.get("title", "")).strip(),
                url=url,
                snippet=str(item.get("content", "")).strip(),
            )
        )
    return results


def _search_brave(query: str, limit: int, api_key: str) -> list[SearchResult]:
    response = httpx.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": limit},
        headers={"Accept": "application/json", "X-Subscription-Token": api_key},
        timeout=SEARCH_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    results: list[SearchResult] = []
    for item in payload.get("web", {}).get("results", []):
        url = str(item.get("url", "")).strip()
        if not url:
            continue
        results.append(
            SearchResult(
                title=str(item.get("title", "")).strip(),
                url=url,
                snippet=str(item.get("description", "")).strip(),
            )
        )
    return results


def resolve_search_provider(provider: str | None = None) -> str | None:
    """Pick the search backend from an explicit value, env, or available keys."""
    requested = (provider or os.getenv("HEADROOM_AGENT_SEARCH_PROVIDER") or "auto").strip().lower()
    has_brave = bool(os.getenv("BRAVE_API_KEY", "").strip())
    has_tavily = bool(os.getenv("TAVILY_API_KEY", "").strip())
    if requested == "brave":
        return "brave" if has_brave else None
    if requested == "tavily":
        return "tavily" if has_tavily else None
    if has_tavily:
        return "tavily"
    if has_brave:
        return "brave"
    return None


def search_web(query: str, limit: int, provider: str | None = None) -> tuple[list[SearchResult], str | None]:
    """Run a web search and return (results, provider_used)."""
    resolved = resolve_search_provider(provider)
    if resolved is None:
        return [], None
    if resolved == "tavily":
        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        return _search_tavily(query, limit, api_key), resolved
    api_key = os.getenv("BRAVE_API_KEY", "").strip()
    return _search_brave(query, limit, api_key), resolved
