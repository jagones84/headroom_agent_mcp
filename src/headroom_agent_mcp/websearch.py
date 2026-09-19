"""Web search and readable-content extraction helpers for the discovery subagent."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

SEARCH_TIMEOUT_SECONDS = 20.0
FETCH_TIMEOUT_SECONDS = 20.0
FETCH_MAX_CHARS = 2_000_000
USER_AGENT = "headroom-agent-discovery/0.1 (+https://github.com/jagones84/headroom_agent_mcp)"
DUCKDUCKGO_ENDPOINT = "https://html.duckduckgo.com/html/"
DUCKDUCKGO_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_PROVIDER_ORDER = ("tavily", "brave", "duckduckgo")

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


def _decode_duckduckgo_url(href: str) -> str:
    """Unwrap DuckDuckGo's redirect link into the real destination URL."""
    if not href:
        return ""
    target = href
    if target.startswith("//"):
        target = f"https:{target}"
    parsed = urlparse(target)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        redirected = parse_qs(parsed.query).get("uddg", [""])[0]
        if redirected:
            return unquote(redirected)
    return target


class _DuckDuckGoParser(HTMLParser):
    """Dependency-free parser for the DuckDuckGo HTML results page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._title_parts: list[str] = []
        self._current_url = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag == "a" and "result__a" in classes:
            self._in_title = True
            self._title_parts = []
            self._current_url = dict(attrs).get("href") or ""
        elif "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            url = _decode_duckduckgo_url(self._current_url)
            if url:
                self.results.append({"title": "".join(self._title_parts).strip(), "url": url, "snippet": ""})
        elif self._in_snippet and tag in {"a", "div", "span"}:
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_snippet and self.results:
            self.results[-1]["snippet"] += data


def _search_duckduckgo(query: str, limit: int, api_key: str | None = None) -> list[SearchResult]:
    """Keyless DuckDuckGo fallback via the no-JS HTML endpoint."""
    response = httpx.post(
        DUCKDUCKGO_ENDPOINT,
        data={"q": query},
        headers={"User-Agent": DUCKDUCKGO_USER_AGENT},
        timeout=SEARCH_TIMEOUT_SECONDS,
        follow_redirects=True,
    )
    response.raise_for_status()
    parser = _DuckDuckGoParser()
    parser.feed(response.text)
    results: list[SearchResult] = []
    for item in parser.results:
        if not item["url"]:
            continue
        results.append(
            SearchResult(
                title=item["title"],
                url=item["url"],
                snippet=item["snippet"].strip(),
            )
        )
        if len(results) >= limit:
            break
    return results


def _provider_available(name: str) -> bool:
    """Report whether a provider can run with the current environment."""
    if name == "tavily":
        return bool(os.getenv("TAVILY_API_KEY", "").strip())
    if name == "brave":
        return bool(os.getenv("BRAVE_API_KEY", "").strip())
    if name == "duckduckgo":
        return True
    return False


def resolve_search_chain(provider: str | None = None) -> list[str]:
    """Return the ordered providers to try, honouring an explicit preference.

    Sources: search/provider selection extends the existing auto behaviour with a
    keyless fallback; DuckDuckGo has no official API, so it is used last.
    """
    requested = (provider or os.getenv("HEADROOM_AGENT_SEARCH_PROVIDER") or "auto").strip().lower()
    order = list(DEFAULT_PROVIDER_ORDER)
    if requested in DEFAULT_PROVIDER_ORDER:
        order.remove(requested)
        order.insert(0, requested)
    return [name for name in order if _provider_available(name)]


def resolve_search_provider(provider: str | None = None) -> str | None:
    """Pick the first usable search backend from an explicit value, env, or keys."""
    chain = resolve_search_chain(provider)
    return chain[0] if chain else None


def search_web(query: str, limit: int, provider: str | None = None) -> tuple[list[SearchResult], str | None]:
    """Run a web search trying each provider in order and return (results, provider_used)."""
    chain = resolve_search_chain(provider)
    if not chain:
        return [], None
    failures: list[str] = []
    for name in chain:
        try:
            if name == "tavily":
                results = _search_tavily(query, limit, os.getenv("TAVILY_API_KEY", "").strip())
            elif name == "brave":
                results = _search_brave(query, limit, os.getenv("BRAVE_API_KEY", "").strip())
            else:
                results = _search_duckduckgo(query, limit)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        if results:
            return results, name
        failures.append(f"{name}: no results")
    if failures and all("no results" not in failure for failure in failures):
        raise RuntimeError("; ".join(failures))
    return [], chain[-1]
