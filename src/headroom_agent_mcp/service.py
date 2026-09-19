"""Goal-shaped discovery service used by the MCP tool."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import RequestDefaults
from .llm import OpenAICompatibleLLMClient, UnresolvedCCRRetrievalError
from .models import (
    CandidateFile,
    CandidateSymbol,
    CommandAllowlistProfile,
    DiscoveryRequest,
    DiscoveryResponse,
    ObjectiveType,
    SmallSnippet,
)
from .terminal import run_allowed_commands
from .websearch import (
    bm25_scores,
    content_fingerprint,
    dedupe_search_results,
    fetch_url_readable,
    search_web,
)


SKIP_DIR_NAMES = {".git", "node_modules", ".venv", "__pycache__", ".pytest_cache", "dist", "build"}
TEXT_FILE_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".log",
    ".ini",
    ".cfg",
    ".toml",
    ".sh",
}
TEXT_FILE_NAMES = {
    ".env",
    ".env.template",
    "dockerfile",
    "makefile",
    "procfile",
}
TEXT_READ_LIMIT = 20_000
EVIDENCE_SECTION_CHARS = 1200
TEST_DIR_NAMES = {"tests", "test", "__tests__", "spec", "specs"}
MAX_LOG_FINDINGS = 8
SEVERITY_RANK_PATTERNS = (
    (re.compile(r"\b(error|critical|fatal|exception|traceback|fail|failed|timeout)\b", re.IGNORECASE), 0),
    (re.compile(r"\b(warn|warning)\b", re.IGNORECASE), 1),
    (re.compile(r"\b(info|debug|notice|verbose)\b", re.IGNORECASE), 2),
)


@dataclass
class EvidenceDocument:
    path: str
    text: str
    score: float
    truncated: bool = False


class DiscoveryService:
    """Collect scoped evidence and shape it for the parent agent."""

    def __init__(
        self,
        *,
        llm_client: OpenAICompatibleLLMClient | None = None,
        default_model_profile: str | None = None,
        request_defaults: RequestDefaults | dict[str, object] | None = None,
        command_profiles: dict[CommandAllowlistProfile, list[list[str]]] | None = None,
        llm_evidence_char_budget: int = 12000,
    ) -> None:
        self.llm_client = llm_client
        self.default_model_profile = default_model_profile
        self.request_defaults = (
            request_defaults
            if isinstance(request_defaults, RequestDefaults)
            else RequestDefaults.model_validate(request_defaults or {})
        )
        self.command_profiles = command_profiles or {}
        self.llm_evidence_char_budget = max(int(llm_evidence_char_budget), 1000)
        self.url_text_limit = max(TEXT_READ_LIMIT, self.llm_evidence_char_budget)
        self._llm_documents: list[EvidenceDocument] = []

    def run(self, request: DiscoveryRequest) -> DiscoveryResponse:
        request = self._apply_request_defaults(request)
        self._llm_documents = []
        if request.objective_type is ObjectiveType.CODEBASE_DISCOVERY:
            response = self._run_codebase_discovery(request)
        elif request.objective_type is ObjectiveType.LOGS_TRIAGE:
            response = self._run_logs_triage(request)
        elif request.objective_type is ObjectiveType.WEB_RESEARCH:
            response = self._run_web_research(request)
        else:
            response = self._run_docs_research(request)

        effective_model_profile = request.model_profile or self.default_model_profile
        if effective_model_profile and self.llm_client:
            response = self._maybe_enrich_with_llm(request, response, effective_model_profile)
        return response

    def _apply_request_defaults(self, request: DiscoveryRequest) -> DiscoveryRequest:
        payload = request.model_dump()
        for field_name in ("command_allowlist_profile", "max_files", "max_commands", "raw_read_budget", "return_snippets"):
            if field_name not in request.model_fields_set:
                payload[field_name] = getattr(self.request_defaults, field_name)
        return DiscoveryRequest.model_validate(payload)

    def _run_codebase_discovery(self, request: DiscoveryRequest) -> DiscoveryResponse:
        command_results = self._run_terminal_commands(request)
        documents = self._collect_documents(request)
        candidate_documents = documents[: request.max_files]
        candidate_files = [
            CandidateFile(path=doc.path, reason=self._candidate_reason(doc.score), score=round(doc.score, 2))
            for doc in candidate_documents
        ]
        candidate_symbols = self._extract_symbols(candidate_documents)
        snippets = self._build_snippets(documents, request)
        findings = [
            self._candidate_finding(doc)
            for doc in documents[: min(4, len(documents))]
        ]
        raw_reads = [item.path for item in candidate_files[: request.raw_read_budget]]
        has_keyword_match = any(doc.score > 0 for doc in candidate_documents)
        return DiscoveryResponse(
            summary=(
                f"Found {len(candidate_files)} candidate files for '{request.objective}'. "
                "Use the raw reads list before editing."
            ),
            objective_type=request.objective_type,
            relevant_findings=findings or ["No strong file match found; broaden query_hints or scope_paths."],
            candidate_files=candidate_files,
            candidate_symbols=candidate_symbols,
            small_snippets=snippets if request.return_snippets else [],
            commands_run=command_results,
            raw_reads_needed_by_parent=raw_reads,
            uncertainties=self._truncation_uncertainties(candidate_documents) + [
                "This tool narrows the search space but does not replace raw file reads for final edits.",
            ],
            recommended_next_action=(
                "Open the top raw_reads_needed_by_parent files raw, then patch only after confirming the exact symbol."
            ),
            confidence="medium" if has_keyword_match else "low",
        )

    def _run_logs_triage(self, request: DiscoveryRequest) -> DiscoveryResponse:
        command_results = self._run_terminal_commands(request)
        documents = self._collect_documents(request)
        production_documents = [doc for doc in documents if not self._is_test_path(doc.path)]
        documents = production_documents or documents
        findings = self._rank_and_dedupe_findings(
            self._extract_error_findings(documents, command_results, request.query_hints)
        )
        candidate_files = [
            CandidateFile(
                path=doc.path,
                reason=self._candidate_reason(doc.score, "Contains log/error evidence"),
                score=round(doc.score, 2),
            )
            for doc in documents[: request.max_files]
        ]
        raw_reads = [item.path for item in candidate_files[: request.raw_read_budget]]
        snippets = self._build_snippets(documents, request)
        return DiscoveryResponse(
            summary=(
                f"Collected {len(findings)} relevant log findings across {len(candidate_files)} candidate files/outputs."
            ),
            objective_type=request.objective_type,
            relevant_findings=findings or ["No error-pattern lines found; inspect full logs raw."],
            candidate_files=candidate_files,
            candidate_symbols=[],
            small_snippets=snippets if request.return_snippets else [],
            commands_run=command_results,
            raw_reads_needed_by_parent=raw_reads,
            uncertainties=self._truncation_uncertainties(documents[: request.max_files]) + [
                "Correlate these findings with the raw log sections before deciding on a fix.",
            ],
            recommended_next_action=(
                "Read the top raw log file raw and follow the first failing stack frame or timeout boundary."
            ),
            confidence="medium" if findings else "low",
        )

    def _build_search_query(self, request: DiscoveryRequest) -> str:
        """Combine the objective with a few hints into a single search query."""
        hints = [hint.strip() for hint in request.query_hints if hint.strip()]
        if hints:
            return f"{request.objective} {' '.join(hints[:4])}".strip()
        return request.objective.strip()

    def _run_web_research(self, request: DiscoveryRequest) -> DiscoveryResponse:
        """Delegate the whole web search to the subagent.

        The parent passes an objective, not URLs: this mode searches the web, fetches the
        results, extracts readable text, and hands the (large) evidence to the proxied LLM so
        Headroom compresses it instead of the parent context absorbing it.
        """
        query = self._build_search_query(request)
        search_error = ""
        try:
            results, provider = search_web(query, request.search_results_limit, request.search_provider)
        except Exception as exc:
            results, provider, search_error = [], None, str(exc)

        # Shape the result list before paying for a fetch on each entry: backends
        # return several pages per site and can serve the same URL twice.
        unique_results = dedupe_search_results(results)

        documents: list[EvidenceDocument] = []
        findings: list[str] = []
        ranked_text: list[str] = []
        seen_content: set[str] = set()
        content_duplicates = 0
        for result in unique_results:
            text, truncated = self._fetch_url(result.url)
            if not text:
                text = result.snippet
                truncated = False
            if not text.strip():
                continue
            fingerprint = content_fingerprint(text)
            if fingerprint and fingerprint in seen_content:
                content_duplicates += 1
                continue
            seen_content.add(fingerprint)
            documents.append(
                EvidenceDocument(path=result.url, text=text, score=0.0, truncated=truncated)
            )
            # The title is part of what the backend matched on, so it feeds the
            # reranker even though only the body becomes evidence.
            ranked_text.append(f"{result.title}\n{text}")
            if result.snippet:
                findings.append(f"{result.title or result.url}: {result.snippet[:200]}")

        for document, score in zip(documents, bm25_scores(ranked_text, query)):
            document.score = score
        documents.sort(key=lambda item: item.score, reverse=True)
        candidate_files = [
            CandidateFile(path=doc.path, reason="Web search result", score=round(doc.score, 2))
            for doc in documents[: request.max_files]
        ]
        snippets = self._build_snippets(documents, request)
        self._llm_documents = documents

        uncertainties = self._truncation_uncertainties(documents[: request.max_files])
        dropped_results = len(results) - len(unique_results)
        if dropped_results > 0:
            uncertainties.append(
                f"Dropped {dropped_results} duplicate search result(s) (same URL or an over-represented "
                "domain) before fetching; raise search_results_limit or vary the objective to widen coverage."
            )
        if content_duplicates > 0:
            uncertainties.append(
                f"Skipped {content_duplicates} page(s) whose readable text duplicated an earlier source."
            )
        if search_error:
            uncertainties.append(f"Web search failed: {search_error}")
        elif provider is None:
            uncertainties.append(
                "No web search provider available: set BRAVE_API_KEY or TAVILY_API_KEY, or pass search_provider."
            )
        elif not documents:
            uncertainties.append(f"Provider '{provider}' returned no usable page content for query '{query}'.")
        else:
            uncertainties.append("Cross-check these extracted pages against their sources before acting.")

        return DiscoveryResponse(
            summary=(
                f"Web research via {provider or 'no provider'}: {len(documents)} readable sources for '{query}'."
            ),
            objective_type=request.objective_type,
            relevant_findings=findings or ["No readable web evidence collected."],
            candidate_files=candidate_files,
            candidate_symbols=[],
            small_snippets=snippets if request.return_snippets else [],
            commands_run=[],
            raw_reads_needed_by_parent=[item.path for item in candidate_files[: request.raw_read_budget]],
            uncertainties=uncertainties,
            recommended_next_action=(
                "Use the extracted text as primary evidence; open the original URL only if a detail is contested."
            ),
            confidence="medium" if documents else "low",
        )

    def _run_docs_research(self, request: DiscoveryRequest) -> DiscoveryResponse:
        command_results = self._run_terminal_commands(request)
        documents = self._collect_documents(request)
        candidate_files = [
            CandidateFile(
                path=doc.path,
                reason=self._candidate_reason(doc.score, "Relevant documentation hit"),
                score=round(doc.score, 2),
            )
            for doc in documents[: request.max_files]
        ]
        snippets = self._build_snippets(documents, request)
        findings = self._build_grounded_doc_findings(documents, snippets)
        raw_reads = [item.path for item in candidate_files[: request.raw_read_budget]]
        return DiscoveryResponse(
            summary=f"Collected {len(candidate_files)} documentation candidates for '{request.objective}'.",
            objective_type=request.objective_type,
            relevant_findings=findings or ["No documentation candidates found in scope."],
            candidate_files=candidate_files,
            candidate_symbols=[],
            small_snippets=snippets if request.return_snippets else [],
            commands_run=command_results,
            raw_reads_needed_by_parent=raw_reads,
            uncertainties=self._truncation_uncertainties(documents[: request.max_files]) + [
                "External docs and local docs may diverge; validate against the source of truth.",
            ],
            recommended_next_action="Open the top raw doc candidates and cite the exact sections you will rely on.",
            confidence="medium" if candidate_files else "low",
        )

    def _collect_documents(self, request: DiscoveryRequest) -> list[EvidenceDocument]:
        terms = self._search_terms(request)
        documents: list[EvidenceDocument] = []
        for scope in request.scope_paths or ["."]:
            if scope.startswith(("http://", "https://")):
                fetched, truncated = self._fetch_url(scope)
                if fetched:
                    documents.append(
                        EvidenceDocument(
                            path=scope,
                            text=fetched,
                            score=self._score_text(scope, fetched, terms),
                            truncated=truncated,
                        )
                    )
                continue
            path = Path(scope)
            if path.is_file():
                text, truncated = self._read_text_file(path)
                if text:
                    documents.append(
                        EvidenceDocument(
                            path=str(path),
                            text=text,
                            score=self._score_text(str(path), text, terms),
                            truncated=truncated,
                        )
                    )
                continue
            if path.is_dir():
                for file_path in self._iter_text_files(path):
                    text, truncated = self._read_text_file(file_path)
                    if text:
                        documents.append(
                            EvidenceDocument(
                                path=str(file_path),
                                text=text,
                                score=self._score_text(str(file_path), text, terms),
                                truncated=truncated,
                            )
                        )
        documents.sort(key=lambda item: item.score, reverse=True)
        positive_docs = [doc for doc in documents if doc.score > 0]
        selected = positive_docs or documents
        return selected[: max(request.max_files * 3, request.raw_read_budget)]

    def _search_terms(self, request: DiscoveryRequest) -> list[str]:
        base_terms = re.findall(r"[a-zA-Z_]{3,}", request.objective.lower())
        return list(dict.fromkeys(base_terms + [hint.lower() for hint in request.query_hints if hint.strip()]))

    def _iter_text_files(self, root: Path):
        for path in root.rglob("*"):
            if self._should_skip_path(path):
                continue
            if path.is_file() and self._is_text_path(path):
                yield path

    def _should_skip_path(self, path: Path) -> bool:
        return any(part in SKIP_DIR_NAMES or part.endswith(".egg-info") for part in path.parts)

    def _is_text_path(self, path: Path) -> bool:
        if path.suffix.lower() in TEXT_FILE_SUFFIXES:
            return True
        lowered_name = path.name.lower()
        return lowered_name in TEXT_FILE_NAMES or lowered_name.startswith(".env")

    def _read_text_file(self, path: Path) -> tuple[str, bool]:
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                text = handle.read(TEXT_READ_LIMIT + 1)
            truncated = len(text) > TEXT_READ_LIMIT
            return text[:TEXT_READ_LIMIT], truncated
        except OSError:
            return "", False

    def _fetch_url(self, url: str) -> tuple[str, bool]:
        """Fetch a URL, extract readable text, then bound it to the preview budget."""
        text, truncated = fetch_url_readable(url)
        if not text:
            return "", False
        if len(text) > self.url_text_limit:
            return text[: self.url_text_limit], True
        return text, truncated

    def _score_text(self, path: str, text: str, terms: list[str]) -> float:
        if not terms:
            return 1.0
        path_terms = re.findall(r"[a-zA-Z0-9_]+", path.lower())
        text_terms = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        text_weight = max(len(text_terms), 1)
        score = 0.0
        for term in terms:
            score += path_terms.count(term) * 3
            score += (text_terms.count(term) * 100.0) / text_weight
        return score

    def _candidate_reason(self, score: float, matched_reason: str = "High keyword overlap with objective") -> str:
        if score > 0:
            return matched_reason
        return "No keyword match; included as a best-effort fallback candidate."

    def _candidate_finding(self, doc: EvidenceDocument) -> str:
        if doc.score > 0:
            return f"{Path(doc.path).name}: matched discovery terms with score {round(doc.score, 2)}"
        return f"{Path(doc.path).name}: fallback candidate with no exact keyword match"

    def _extract_symbols(self, documents: list[EvidenceDocument]) -> list[CandidateSymbol]:
        symbols: list[CandidateSymbol] = []
        seen: set[tuple[str, str]] = set()
        patterns = [
            (re.compile(r"^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE), "function"),
            (re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE), "class"),
            (re.compile(r"^\s*(?:export\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE), "function"),
            (re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE), "constant"),
        ]
        for doc in documents:
            for pattern, kind in patterns:
                for match in pattern.finditer(doc.text):
                    key = (doc.path, match.group(1))
                    if key in seen:
                        continue
                    seen.add(key)
                    symbols.append(
                        CandidateSymbol(
                            symbol=match.group(1),
                            path=doc.path,
                            kind=kind,
                            reason="Declared in a top-ranked candidate file.",
                        )
                    )
                    if len(symbols) >= 12:
                        return symbols
        return symbols

    @staticmethod
    def _match_offset(lines: list[str], start: int, matched_index: int, terms: list[str]) -> int:
        line_offset = sum(len(lines[index]) + 1 for index in range(start, matched_index))
        matched_line_lower = lines[matched_index].lower()
        columns = [matched_line_lower.find(term) for term in terms]
        columns = [column for column in columns if column != -1]
        column = min(columns) if columns else 0
        return line_offset + column

    @staticmethod
    def _excerpt_around_match(block: str, match_offset: int, max_chars: int) -> str:
        if max_chars <= 0 or len(block) <= max_chars or match_offset < max_chars:
            return block[:max_chars]
        half = max_chars // 2
        window_start = max(match_offset - half, 0)
        window_end = window_start + max_chars
        prefix = "…" if window_start > 0 else ""
        suffix = "…" if window_end < len(block) else ""
        return prefix + block[window_start:window_end] + suffix

    def _build_snippets(self, documents: list[EvidenceDocument], request: DiscoveryRequest) -> list[SmallSnippet]:
        terms = self._search_terms(request)
        snippet_limit = min(max(request.raw_read_budget * 2, 1), 8)
        per_doc_limit = min(5, snippet_limit)
        snippets_by_doc: list[list[SmallSnippet]] = []
        for doc in documents[: request.raw_read_budget]:
            lines = doc.text.splitlines()
            matched_indices = [
                index
                for index, line in enumerate(lines)
                if any(term in line.lower() for term in terms)
            ] or [0]
            covered_until = -1
            snippets_for_doc = 0
            doc_snippets: list[SmallSnippet] = []
            for matched_index in matched_indices:
                start = max(matched_index - 2, 0)
                end = min(matched_index + 3, len(lines))
                if end <= covered_until:
                    continue
                block = "\n".join(lines[start:end])
                match_offset = self._match_offset(lines, start, matched_index, terms)
                snippet = self._excerpt_around_match(
                    block, match_offset, self.request_defaults.max_snippet_chars
                )
                if not snippet.strip():
                    continue
                doc_snippets.append(
                    SmallSnippet(
                        path=doc.path,
                        snippet=snippet,
                        reason="Small raw excerpt around a relevant match.",
                    )
                )
                covered_until = end
                snippets_for_doc += 1
                if snippets_for_doc >= per_doc_limit:
                    break
            if doc_snippets:
                snippets_by_doc.append(doc_snippets)

        snippets: list[SmallSnippet] = []
        round_index = 0
        while len(snippets) < snippet_limit:
            appended_in_round = False
            for doc_snippets in snippets_by_doc:
                if round_index < len(doc_snippets):
                    snippets.append(doc_snippets[round_index])
                    appended_in_round = True
                    if len(snippets) >= snippet_limit:
                        break
            if not appended_in_round:
                break
            round_index += 1
        return snippets

    def _build_grounded_doc_findings(
        self,
        documents: list[EvidenceDocument],
        snippets: list[SmallSnippet],
    ) -> list[str]:
        findings: list[str] = []
        snippet_by_path: dict[str, list[str]] = {}
        for snippet in snippets:
            snippet_by_path.setdefault(snippet.path, []).append(snippet.snippet)
        for doc in documents[: min(4, len(documents))]:
            snippet = "\n".join(snippet_by_path.get(doc.path, [])).strip()
            if snippet:
                snippet_lines = [line.strip() for line in snippet.splitlines() if line.strip()]
                first_line = next((line for line in snippet_lines if not line.startswith("#")), "")
                if not first_line:
                    first_line = snippet_lines[0] if snippet_lines else ""
                findings.append(f"{Path(doc.path).name}: {first_line}")
                continue
            heading = next((line.strip("# ").strip() for line in doc.text.splitlines() if line.startswith("#")), "")
            findings.append(f"{Path(doc.path).name}: {heading or 'top document candidate'}")
        return findings

    @staticmethod
    def _is_test_path(path: str) -> bool:
        """Treat fixture/test directories as non-production evidence for log triage."""
        if "://" in path:
            return False
        return any(part.lower() in TEST_DIR_NAMES for part in Path(path).parts)

    @staticmethod
    def _severity_rank(text: str) -> int:
        """Return a lower rank for more severe log lines."""
        for pattern, rank in SEVERITY_RANK_PATTERNS:
            if pattern.search(text):
                return rank
        return len(SEVERITY_RANK_PATTERNS)

    def _rank_and_dedupe_findings(self, findings: list[str], limit: int = MAX_LOG_FINDINGS) -> list[str]:
        """Deduplicate findings and surface the most severe ones first."""
        seen: set[str] = set()
        unique: list[str] = []
        for finding in findings:
            key = finding.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(finding)
        return sorted(unique, key=self._severity_rank)[:limit]

    def _extract_error_findings(
        self,
        documents: list[EvidenceDocument],
        command_results,
        query_hints: list[str],
        limit: int = MAX_LOG_FINDINGS * 5,
    ) -> list[str]:
        findings: list[str] = []
        hint_terms = [hint.lower() for hint in query_hints if hint.strip()]
        for doc in documents:
            for line in doc.text.splitlines():
                lower = line.lower()
                if re.search(r"(error|exception|traceback|fail|timeout)", line, re.IGNORECASE) or (
                    hint_terms and any(term in lower for term in hint_terms)
                ):
                    findings.append(f"{Path(doc.path).name}: {line.strip()}")
                    if len(findings) >= limit:
                        return findings
        for result in command_results:
            combined = "\n".join(filter(None, [result.stdout, result.stderr]))
            for line in combined.splitlines():
                lower = line.lower()
                if re.search(r"(error|exception|traceback|fail|timeout)", line, re.IGNORECASE) or (
                    hint_terms and any(term in lower for term in hint_terms)
                ):
                    findings.append(f"{' '.join(result.command)}: {line.strip()}")
                    if len(findings) >= limit:
                        return findings
        return findings

    def _first_real_path(self, scope_paths: list[str]) -> Path | None:
        for scope in scope_paths:
            if scope.startswith(("http://", "https://")):
                continue
            path = Path(scope)
            return path if path.is_dir() else path.parent
        return None

    def _run_terminal_commands(self, request: DiscoveryRequest):
        return run_allowed_commands(
            request.terminal_commands,
            request.command_allowlist_profile,
            cwd=self._first_real_path(request.scope_paths),
            max_commands=request.max_commands,
            allowed_commands=self.command_profiles.get(request.command_allowlist_profile),
        )

    def _maybe_enrich_with_llm(
        self,
        request: DiscoveryRequest,
        response: DiscoveryResponse,
        model_profile: str,
    ) -> DiscoveryResponse:
        payload = response.model_dump()
        response_language = self._language_instruction(request.response_language)
        evidence_budget = self.llm_evidence_char_budget
        try:
            llm_json = self._enrich_with_evidence_budget(
                request, response, model_profile, response_language, evidence_budget
            )
        except UnresolvedCCRRetrievalError as exc:
            print(
                f"[headroom_agent_mcp] LLM hit unresolved CCR retrieval "
                f"({exc}); retrying once with metadata-only evidence",
                file=sys.stderr,
            )
            evidence_budget = max(1000, evidence_budget // 2)
            # Metadata-only retry: document sections are what the proxy turns
            # into <<ccr:>> markers, and markers are what make the proxy inject
            # headroom_retrieve (headroom/ccr/tool_injection.py only injects
            # when scan_for_markers finds compressed content). No markers means
            # no tool to call, so the model must answer from what is present.
            try:
                llm_json = self._enrich_with_evidence_budget(
                    request,
                    response,
                    model_profile,
                    response_language,
                    evidence_budget,
                    max_documents=0,
                )
            except Exception as retry_exc:
                return self._enrichment_failure(
                    payload, model_profile, f"{retry_exc} (after one reduced-evidence retry)"
                )
        except Exception as exc:
            return self._enrichment_failure(payload, model_profile, str(exc))

        for key in ("summary", "recommended_next_action", "confidence"):
            if isinstance(llm_json.get(key), str) and llm_json[key]:
                payload[key] = llm_json[key]
        print(
            f"[headroom_agent_mcp] LLM enrichment keys={sorted(llm_json)} "
            f"summary_chars={len(llm_json.get('summary') or '')}",
            file=sys.stderr,
        )
        payload["llm_enriched"] = True
        payload["llm_error"] = None
        payload["llm_profile_used"] = model_profile
        return DiscoveryResponse.model_validate(payload)

    def _enrichment_failure(
        self, payload: dict[str, object], model_profile: str, error: str
    ) -> DiscoveryResponse:
        print(
            f"[headroom_agent_mcp] LLM enrichment failed for profile {model_profile}: {error}",
            file=sys.stderr,
        )
        payload["llm_enriched"] = False
        payload["llm_error"] = error
        payload["llm_profile_used"] = model_profile
        return DiscoveryResponse.model_validate(payload)

    def _enrich_with_evidence_budget(
        self,
        request: DiscoveryRequest,
        response: DiscoveryResponse,
        model_profile: str,
        response_language: str,
        evidence_budget: int,
        max_documents: int | None = None,
    ) -> dict[str, object]:
        grounded_evidence = self._format_llm_evidence(response, evidence_budget, max_documents)
        return self.llm_client.complete_json(
            model_profile,
            system_prompt=(
                "You are a discovery subagent. Keep the output concise, evidence-driven, and never claim edits were made. "
                "Use only the provided evidence. Do not invent files, symbols, environment variables, commands, stack traces, or tools. "
                f"Respond in {response_language}. This output-language instruction overrides any language suggested by the objective, summary, or evidence. "
                'Return only a json object shaped like {"summary": "...", "recommended_next_action": "...", "confidence": "high|medium|low"}. '
                "The evidence is a JSON document whose evidence_items array holds one excerpt per item. "
                "Some excerpts may be shortened by a context compressor: answer from what is present and lower "
                "confidence when unsure; only call a retrieval tool when one specific missing fact blocks the answer, "
                "and never for more than the one or two blocks you need most. Never describe compression, retrieval "
                "plumbing or truncation, and never ask the user to fetch anything."
            ),
            user_prompt=(
                f"Objective: {request.objective}\n"
                f"Type: {request.objective_type.value}\n"
                f"Existing summary: {response.summary}\n"
                f"Relevant findings: {response.relevant_findings}\n"
                f"Raw reads for parent: {response.raw_reads_needed_by_parent}\n"
                f"Evidence JSON:\n{grounded_evidence}\n"
            ),
        )

    def _format_llm_evidence(
        self,
        response: DiscoveryResponse,
        evidence_char_budget: int | None = None,
        max_documents: int | None = None,
    ) -> str:
        """Build the grounded evidence payload handed to the LLM.

        The payload is structured JSON because that is the shape Headroom
        compresses: its ContentRouter routes JSON arrays to SmartCrusher, which
        keeps first/last, error and query-relevant items and drops the rest.
        Measured through the proxy, a JSON evidence payload saves ~74% of prompt
        tokens while the same content as prose saves only ~4%. Each document is
        therefore emitted as one item per section instead of a single text blob.
        """
        remaining = self.llm_evidence_char_budget if evidence_char_budget is None else evidence_char_budget
        documents = self._llm_documents if max_documents is None else self._llm_documents[:max_documents]
        items: list[dict[str, object]] = []
        for item in response.candidate_files[:4]:
            items.append(
                {
                    "kind": "file",
                    "source": item.path,
                    "score": round(item.score, 3),
                    "reason": item.reason,
                }
            )
        for symbol in response.candidate_symbols[:8]:
            items.append(
                {
                    "kind": "symbol",
                    "source": symbol.path,
                    "symbol": symbol.symbol,
                    "reason": symbol.kind,
                }
            )
        for snippet in response.small_snippets[:6]:
            items.append({"kind": "snippet", "source": snippet.path, "text": snippet.snippet})
        for finding in response.relevant_findings[:8]:
            items.append({"kind": "finding", "text": finding})

        for rank, document in enumerate(documents, start=1):
            if remaining <= 0:
                break
            text = document.text[:remaining]
            remaining -= len(text)
            for section_index, section in enumerate(self._split_evidence_sections(text)):
                items.append(
                    {
                        "kind": "document",
                        "rank": rank,
                        "source": document.path,
                        "section": section_index,
                        "score": round(document.score, 3),
                        "text": section,
                    }
                )

        payload = {
            "objective_type": response.objective_type.value,
            "evidence_items": items,
            "uncertainties": list(response.uncertainties),
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _split_evidence_sections(text: str, chunk_chars: int = EVIDENCE_SECTION_CHARS) -> list[str]:
        """Split a document into ranked-sized sections.

        The compressor only has something to discard when the payload holds many
        items, so each section becomes its own JSON item.
        """
        if not text.strip():
            return []
        sections: list[str] = []
        current: list[str] = []
        current_len = 0
        for raw_block in text.split("\n\n"):
            block = raw_block.strip()
            if not block:
                continue
            while len(block) > chunk_chars:
                if current:
                    sections.append("\n\n".join(current))
                    current = []
                    current_len = 0
                sections.append(block[:chunk_chars])
                block = block[chunk_chars:]
            if current and current_len + len(block) > chunk_chars:
                sections.append("\n\n".join(current))
                current = []
                current_len = 0
            current.append(block)
            current_len += len(block)
        if current:
            sections.append("\n\n".join(current))
        return sections

    def _language_instruction(self, response_language: str) -> str:
        normalized = response_language.strip().lower()
        return {
            "en": "English",
            "it": "Italian",
        }.get(normalized, normalized)

    def _truncation_uncertainties(self, documents: list[EvidenceDocument]) -> list[str]:
        truncated_paths = [Path(doc.path).name if "://" not in doc.path else doc.path for doc in documents if doc.truncated]
        if not truncated_paths:
            return []
        preview = ", ".join(truncated_paths[:3])
        if len(truncated_paths) > 3:
            preview += f" (+{len(truncated_paths) - 3} more)"
        return [
            f"Some sources were truncated to a bounded preview: {preview}. "
            "Read them raw before treating missing matches as evidence of absence."
        ]
