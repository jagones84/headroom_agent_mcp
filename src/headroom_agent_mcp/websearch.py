"""Web search and readable-content extraction helpers for the discovery subagent."""

from __future__ import annotations

import math
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlsplit

import httpx

from .cache import TTLCache

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
MAX_RESULTS_PER_DOMAIN = 2
CONTENT_FINGERPRINT_CHARS = 400
TAVILY_SEARCH_DEPTHS = ("basic", "advanced")
TAVILY_DEFAULT_SEARCH_DEPTH = "advanced"
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
HTTP_MAX_ATTEMPTS = 3
HTTP_BACKOFF_SECONDS = 0.5
RETRY_AFTER_MAX_SECONDS = 5.0
TRACKING_PARAM_PREFIXES = ("utm_",)
TRACKING_PARAM_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "yclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "ref_src",
    "ref_url",
}
BM25_K1 = 1.5
BM25_B = 0.75
BM25_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")

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


_CACHE: TTLCache | None = None


def get_cache() -> TTLCache:
    """Return the process-wide cache, built from the environment on first use."""
    global _CACHE
    if _CACHE is None:
        _CACHE = TTLCache()
    return _CACHE


def reset_cache() -> None:
    """Drop the cached instance so the next call re-reads the environment."""
    global _CACHE
    _CACHE = None


class TransientStatusError(RuntimeError):
    """A retryable HTTP status (429/5xx) that survived every attempt."""

    def __init__(self, status_code: int, retry_after: float | None = None) -> None:
        self.status_code = status_code
        self.retry_after = retry_after
        super().__init__(f"retryable HTTP status {status_code}")


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Read ``Retry-After`` in seconds, capped so a hostile header cannot stall the tool.

    Source: RFC 9110 §10.2.3, https://www.rfc-editor.org/rfc/rfc9110#field.retry-after
    (the HTTP-date form is deliberately ignored; only delay-seconds is honoured).
    """
    raw = str(response.headers.get("retry-after", "")).strip()
    if not raw:
        return None
    try:
        return min(max(float(raw), 0.0), RETRY_AFTER_MAX_SECONDS)
    except ValueError:
        return None


def _retry_delay(retry_after: float | None, attempt: int) -> float:
    """Prefer the server's ``Retry-After``, else linear backoff scaled by the attempt."""
    if retry_after is not None:
        return retry_after
    return HTTP_BACKOFF_SECONDS * attempt


def _request_with_retries(
    method: str,
    url: str,
    *,
    sleep: Callable[[float], None] | None = None,
    **kwargs: object,
) -> httpx.Response:
    """Issue an HTTP request, retrying transient failures with backoff.

    Search backends throttle bursts with 429/503 — DuckDuckGo's no-JS endpoint in
    particular — and one dropped connection should not fail a whole discovery run.

    Sources:
    - RFC 9110 §10.2.3 Retry-After: https://www.rfc-editor.org/rfc/rfc9110#field.retry-after
    - Google API design guide, retrying transient errors with backoff:
      https://cloud.google.com/apis/design/errors#error_retries
    """
    sleeper = sleep or time.sleep
    last_response: httpx.Response | None = None
    last_error: httpx.TransportError | None = None
    for attempt in range(1, HTTP_MAX_ATTEMPTS + 1):
        try:
            response = httpx.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.TransportError as exc:
            last_error = exc
            if attempt >= HTTP_MAX_ATTEMPTS:
                raise
            sleeper(_retry_delay(None, attempt))
            continue
        if response.status_code in RETRY_STATUS_CODES:
            last_response = response
            if attempt >= HTTP_MAX_ATTEMPTS:
                raise TransientStatusError(response.status_code, _retry_after_seconds(response))
            sleeper(_retry_delay(_retry_after_seconds(response), attempt))
            continue
        return response
    if last_response is not None:
        raise TransientStatusError(last_response.status_code, _retry_after_seconds(last_response))
    raise last_error or RuntimeError("HTTP request failed")


def _stream_readable(url: str) -> tuple[str, str, bool]:
    """Single bounded streaming attempt: ``(raw_body, content_type, truncated)``.

    The body is consumed in chunks so a multi-megabyte page never lands in memory
    whole, and a retryable status is surfaced before any content is read.
    """
    with httpx.stream(
        "GET",
        url,
        timeout=FETCH_TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as response:
        if response.status_code in RETRY_STATUS_CODES:
            raise TransientStatusError(response.status_code, _retry_after_seconds(response))
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
        return "".join(parts), content_type, truncated


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


def _stream_readable_with_retries(
    url: str,
    *,
    sleep: Callable[[float], None] | None = None,
) -> tuple[str, str, bool] | None:
    """Stream a URL, retrying transport failures and retryable statuses.

    Returns ``None`` when the page cannot be retrieved, so the caller can fall
    back to the search snippet instead of failing the whole run.
    """
    sleeper = sleep or time.sleep
    for attempt in range(1, HTTP_MAX_ATTEMPTS + 1):
        try:
            return _stream_readable(url)
        except TransientStatusError as exc:
            if attempt >= HTTP_MAX_ATTEMPTS:
                return None
            sleeper(_retry_delay(exc.retry_after, attempt))
        except httpx.TransportError:
            if attempt >= HTTP_MAX_ATTEMPTS:
                return None
            sleeper(_retry_delay(None, attempt))
        except httpx.HTTPError:
            return None
    return None


def fetch_url_readable(url: str) -> tuple[str, bool]:
    """Fetch a URL and return its readable text plus a truncation flag.

    The byte cap protects memory; readability extraction happens before any
    preview limit so HTML `<head>` boilerplate never becomes the evidence.
    Successful pages are cached by canonical URL, so re-running the same objective
    does not re-pay for the download or repeat the extraction.
    """
    cache = get_cache()
    cache_key = f"fetch::{canonicalize_url(url) or url}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict):
        return str(cached.get("text", "")), bool(cached.get("truncated", False))

    streamed = _stream_readable_with_retries(url)
    if streamed is None:
        return "", False
    raw, content_type, truncated = streamed
    text = extract_readable_text(raw) if _looks_like_html(raw, content_type) else raw
    cache.set(cache_key, {"text": text, "truncated": truncated})
    return text, truncated


def tavily_search_depth() -> str:
    """Return the Tavily retrieval depth, defaulting to the higher-recall mode.

    ``advanced`` returns more relevant chunks per result at a higher credit cost;
    set ``HEADROOM_AGENT_TAVILY_SEARCH_DEPTH=basic`` to trade recall for credits.
    Source: https://docs.tavily.com/documentation/api-reference/endpoint/search
    """
    depth = os.getenv("HEADROOM_AGENT_TAVILY_SEARCH_DEPTH", TAVILY_DEFAULT_SEARCH_DEPTH)
    depth = depth.strip().lower()
    return depth if depth in TAVILY_SEARCH_DEPTHS else TAVILY_DEFAULT_SEARCH_DEPTH


def _search_tavily(query: str, limit: int, api_key: str) -> list[SearchResult]:
    response = _request_with_retries(
        "POST",
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "max_results": limit,
            "search_depth": tavily_search_depth(),
        },
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
    response = _request_with_retries(
        "GET",
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
    response = _request_with_retries(
        "POST",
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
    """Run a web search trying each provider in order and return (results, provider_used).

    Successful result sets are cached, so repeating an objective inside the TTL
    does not spend another search credit. Failures and empty result sets are not
    cached: they are exactly the cases where a retry should reach the network.
    """
    chain = resolve_search_chain(provider)
    if not chain:
        return [], None

    cache = get_cache()
    cache_key = f"search::{provider or 'auto'}::{limit}::{query.strip().lower()}"
    cached = cache.get(cache_key)
    if isinstance(cached, dict) and cached.get("results"):
        return [SearchResult(**item) for item in cached["results"]], cached.get("provider")

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
            cache.set(cache_key, {"provider": name, "results": [asdict(item) for item in results]})
            return results, name
        failures.append(f"{name}: no results")
    if failures and all("no results" not in failure for failure in failures):
        raise RuntimeError("; ".join(failures))
    return [], chain[-1]


def domain_of(url: str) -> str:
    """Return the host of a URL without a leading ``www.``."""
    host = urlsplit(url.strip()).netloc.lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


def canonicalize_url(url: str) -> str:
    """Return a stable comparison key for a result URL.

    Dedup keys must ignore everything that does not change which document is
    served: the fragment (never sent to the server) and tracking parameters.
    The scheme is dropped too, so ``http`` and ``https`` copies of one page
    collapse together.

    Sources:
    - URL Standard, fragment is not part of what the server receives:
      https://url.spec.whatwg.org/#concept-url-fragment
    - RFC 3986 §6.2.2, syntax-based normalization (case, default port):
      https://www.rfc-editor.org/rfc/rfc3986#section-6.2.2
    """
    if not url or not url.strip():
        return ""
    parts = urlsplit(url.strip())
    host = domain_of(url)
    if not host:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAM_KEYS
        and not key.lower().startswith(TRACKING_PARAM_PREFIXES)
    ]
    path = parts.path.rstrip("/") or "/"
    serialized = f"{host}{path}"
    if query:
        serialized = f"{serialized}?{urlencode(query)}"
    return serialized


def dedupe_search_results(
    results: list[SearchResult],
    *,
    max_per_domain: int = MAX_RESULTS_PER_DOMAIN,
) -> list[SearchResult]:
    """Drop duplicate URLs and cap how many results a single domain contributes.

    Search backends happily return several pages from one site, and a mirror of
    the same page can appear twice. Without shaping, the fetched evidence can be
    five views of one source. Input order is preserved, so the backend's own
    ranking decides which of a domain's results survive.
    """
    seen_urls: set[str] = set()
    per_domain: Counter[str] = Counter()
    kept: list[SearchResult] = []
    for result in results:
        key = canonicalize_url(result.url)
        if not key or key in seen_urls:
            continue
        domain = domain_of(result.url)
        if max_per_domain > 0 and per_domain[domain] >= max_per_domain:
            continue
        seen_urls.add(key)
        per_domain[domain] += 1
        kept.append(result)
    return kept


def content_fingerprint(text: str, chars: int = CONTENT_FINGERPRINT_CHARS) -> str:
    """Return a cheap identity key for readable page text.

    Mirrors and syndicated copies share their opening text, so a normalized
    prefix catches the common case without hashing whole documents.
    """
    normalized = re.sub(r"\s+", " ", text.strip().lower())
    return normalized[:chars]


def bm25_scores(
    documents: list[str],
    query: str,
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> list[float]:
    """Score each document against the query with Okapi BM25 (zero dependencies).

    Ranking a small result set by raw keyword counts over-rewards long pages and
    cannot tell a discriminative term from a common one. BM25 fixes both: term
    frequency saturates via ``k1``, is length-normalised via ``b``, and every
    term is weighted by inverse document frequency across the candidate set.

    Per query term present in a document:
        IDF(q) * f(q,D) * (k1 + 1) / (f(q,D) + k1 * (1 - b + b * |D| / avgdl))
        IDF(q) = ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1)

    The floored IDF is the Lucene/Elasticsearch variant: it stays non-negative
    even for a term present in more than half the documents.

    Sources:
    - Robertson & Zaragoza, "The Probabilistic Relevance Framework: BM25 and
      Beyond", Foundations and Trends in IR (2009), https://doi.org/10.1561/1500000019
    - Apache Lucene `BM25Similarity` (same shapes and the k1/b defaults):
      https://lucene.apache.org/core/9_0_0/core/org/apache/lucene/search/similarities/BM25Similarity.html
    """
    if not documents:
        return []
    tokenized = [BM25_TOKEN_PATTERN.findall(document.lower()) for document in documents]
    query_terms = list(dict.fromkeys(BM25_TOKEN_PATTERN.findall(query.lower())))
    if not query_terms:
        return [0.0 for _ in documents]

    doc_count = len(tokenized)
    average_length = sum(len(tokens) for tokens in tokenized) / doc_count or 1.0
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))

    idf = {
        term: math.log(
            (doc_count - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5) + 1.0
        )
        for term in query_terms
        if term in document_frequency
    }

    scores: list[float] = []
    for tokens in tokenized:
        length = len(tokens) or 1
        frequencies = Counter(tokens)
        normalizer = k1 * (1 - b + b * length / average_length)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            score += idf[term] * frequency * (k1 + 1) / (frequency + normalizer)
        scores.append(score)
    return scores
