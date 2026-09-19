"""Goal-shaped discovery service used by the MCP tool."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import RequestDefaults
from .llm import OpenAICompatibleLLMClient
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


@dataclass
class EvidenceDocument:
    path: str
    text: str
    score: float


class DiscoveryService:
    """Collect scoped evidence and shape it for the parent agent."""

    def __init__(
        self,
        *,
        llm_client: OpenAICompatibleLLMClient | None = None,
        default_model_profile: str | None = None,
        request_defaults: RequestDefaults | dict[str, object] | None = None,
        command_profiles: dict[CommandAllowlistProfile, list[list[str]]] | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.default_model_profile = default_model_profile
        self.request_defaults = (
            request_defaults
            if isinstance(request_defaults, RequestDefaults)
            else RequestDefaults.model_validate(request_defaults or {})
        )
        self.command_profiles = command_profiles or {}

    def run(self, request: DiscoveryRequest) -> DiscoveryResponse:
        request = self._apply_request_defaults(request)
        if request.objective_type is ObjectiveType.CODEBASE_DISCOVERY:
            response = self._run_codebase_discovery(request)
        elif request.objective_type is ObjectiveType.LOGS_TRIAGE:
            response = self._run_logs_triage(request)
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
            commands_run=[],
            raw_reads_needed_by_parent=raw_reads,
            uncertainties=[
                "This tool narrows the search space but does not replace raw file reads for final edits.",
            ],
            recommended_next_action=(
                "Open the top raw_reads_needed_by_parent files raw, then patch only after confirming the exact symbol."
            ),
            confidence="medium" if has_keyword_match else "low",
        )

    def _run_logs_triage(self, request: DiscoveryRequest) -> DiscoveryResponse:
        command_results = run_allowed_commands(
            request.terminal_commands,
            request.command_allowlist_profile,
            cwd=self._first_real_path(request.scope_paths),
            max_commands=request.max_commands,
            allowed_commands=self.command_profiles.get(request.command_allowlist_profile),
        )
        documents = self._collect_documents(request)
        findings = self._extract_error_findings(documents, command_results, request.query_hints)
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
            uncertainties=[
                "Correlate these findings with the raw log sections before deciding on a fix.",
            ],
            recommended_next_action=(
                "Read the top raw log file raw and follow the first failing stack frame or timeout boundary."
            ),
            confidence="medium" if findings else "low",
        )

    def _run_docs_research(self, request: DiscoveryRequest) -> DiscoveryResponse:
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
            commands_run=[],
            raw_reads_needed_by_parent=raw_reads,
            uncertainties=["External docs and local docs may diverge; validate against the source of truth."],
            recommended_next_action="Open the top raw doc candidates and cite the exact sections you will rely on.",
            confidence="medium" if candidate_files else "low",
        )

    def _collect_documents(self, request: DiscoveryRequest) -> list[EvidenceDocument]:
        terms = self._search_terms(request)
        documents: list[EvidenceDocument] = []
        for scope in request.scope_paths or ["."]:
            if scope.startswith(("http://", "https://")):
                fetched = self._fetch_url(scope)
                if fetched:
                    documents.append(EvidenceDocument(path=scope, text=fetched, score=self._score_text(scope, fetched, terms)))
                continue
            path = Path(scope)
            if path.is_file():
                text = self._read_text_file(path)
                if text:
                    documents.append(EvidenceDocument(path=str(path), text=text, score=self._score_text(str(path), text, terms)))
                continue
            if path.is_dir():
                for file_path in self._iter_text_files(path):
                    text = self._read_text_file(file_path)
                    if text:
                        documents.append(
                            EvidenceDocument(
                                path=str(file_path),
                                text=text,
                                score=self._score_text(str(file_path), text, terms),
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

    def _read_text_file(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")[:20000]
        except OSError:
            return ""

    def _fetch_url(self, url: str) -> str:
        try:
            response = httpx.get(url, timeout=15.0, follow_redirects=True)
            response.raise_for_status()
            return response.text[:20000]
        except httpx.HTTPError:
            return ""

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

    def _build_snippets(self, documents: list[EvidenceDocument], request: DiscoveryRequest) -> list[SmallSnippet]:
        snippets: list[SmallSnippet] = []
        terms = self._search_terms(request)
        for doc in documents[: request.raw_read_budget]:
            lines = doc.text.splitlines()
            matched_index = 0
            for index, line in enumerate(lines):
                lower = line.lower()
                if any(term in lower for term in terms):
                    matched_index = index
                    break
            start = max(matched_index - 2, 0)
            end = min(matched_index + 3, len(lines))
            snippet = "\n".join(lines[start:end])[: self.request_defaults.max_snippet_chars]
            if snippet.strip():
                snippets.append(
                    SmallSnippet(
                        path=doc.path,
                        snippet=snippet,
                        reason="Small raw excerpt around the first relevant match.",
                    )
                )
        return snippets

    def _build_grounded_doc_findings(
        self,
        documents: list[EvidenceDocument],
        snippets: list[SmallSnippet],
    ) -> list[str]:
        findings: list[str] = []
        snippet_by_path = {snippet.path: snippet.snippet for snippet in snippets}
        for doc in documents[: min(4, len(documents))]:
            snippet = snippet_by_path.get(doc.path, "").strip()
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

    def _extract_error_findings(self, documents: list[EvidenceDocument], command_results, query_hints: list[str]) -> list[str]:
        findings: list[str] = []
        hint_terms = [hint.lower() for hint in query_hints if hint.strip()]
        for doc in documents:
            for line in doc.text.splitlines():
                lower = line.lower()
                if re.search(r"(error|exception|traceback|fail|timeout)", line, re.IGNORECASE) or (
                    hint_terms and any(term in lower for term in hint_terms)
                ):
                    findings.append(f"{Path(doc.path).name}: {line.strip()}")
                    if len(findings) >= 8:
                        return findings
        for result in command_results:
            combined = "\n".join(filter(None, [result.stdout, result.stderr]))
            for line in combined.splitlines():
                lower = line.lower()
                if re.search(r"(error|exception|traceback|fail|timeout)", line, re.IGNORECASE) or (
                    hint_terms and any(term in lower for term in hint_terms)
                ):
                    findings.append(f"{' '.join(result.command)}: {line.strip()}")
                    if len(findings) >= 8:
                        return findings
        return findings

    def _first_real_path(self, scope_paths: list[str]) -> Path | None:
        for scope in scope_paths:
            if scope.startswith(("http://", "https://")):
                continue
            path = Path(scope)
            return path if path.is_dir() else path.parent
        return None

    def _maybe_enrich_with_llm(
        self,
        request: DiscoveryRequest,
        response: DiscoveryResponse,
        model_profile: str,
    ) -> DiscoveryResponse:
        payload = response.model_dump()
        grounded_evidence = self._format_llm_evidence(response)
        try:
            llm_json = self.llm_client.complete_json(
                model_profile,
                system_prompt=(
                    "You are a discovery subagent. Keep the output concise, evidence-driven, and never claim edits were made. "
                    "Use only the provided evidence. Do not invent files, symbols, environment variables, commands, stack traces, or tools. "
                    "Return JSON with optional keys: summary, recommended_next_action, confidence."
                ),
                user_prompt=(
                    f"Objective: {request.objective}\n"
                    f"Type: {request.objective_type.value}\n"
                    f"Existing summary: {response.summary}\n"
                    f"Relevant findings: {response.relevant_findings}\n"
                    f"Raw reads for parent: {response.raw_reads_needed_by_parent}\n"
                    f"Grounded evidence:\n{grounded_evidence}\n"
                ),
            )
        except Exception as exc:
            print(
                f"[headroom_agent_mcp] LLM enrichment failed for profile {model_profile}: {exc}",
                file=sys.stderr,
            )
            payload["llm_enriched"] = False
            payload["llm_error"] = str(exc)
            payload["llm_profile_used"] = model_profile
            return DiscoveryResponse.model_validate(payload)

        for key in ("summary", "recommended_next_action", "confidence"):
            if isinstance(llm_json.get(key), str) and llm_json[key]:
                payload[key] = llm_json[key]
        payload["llm_enriched"] = True
        payload["llm_error"] = None
        payload["llm_profile_used"] = model_profile
        return DiscoveryResponse.model_validate(payload)

    def _format_llm_evidence(self, response: DiscoveryResponse) -> str:
        evidence_lines: list[str] = []
        for item in response.candidate_files[:4]:
            evidence_lines.append(f"FILE {item.path} | score={item.score} | reason={item.reason}")
        for symbol in response.candidate_symbols[:8]:
            evidence_lines.append(f"SYMBOL {symbol.path}::{symbol.symbol} | kind={symbol.kind}")
        for snippet in response.small_snippets[:6]:
            evidence_lines.append(f"SNIPPET {snippet.path}:\n{snippet.snippet}")
        for finding in response.relevant_findings[:8]:
            evidence_lines.append(f"FINDING {finding}")
        if not evidence_lines:
            return "(no grounded evidence collected)"
        return "\n---\n".join(evidence_lines)
