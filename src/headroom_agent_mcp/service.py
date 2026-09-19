"""Goal-shaped discovery service used by the MCP tool."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import httpx

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


SKIP_DIR_NAMES = {".git", "node_modules", ".venv", "__pycache__"}
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


@dataclass
class EvidenceDocument:
    path: str
    text: str
    score: float


class DiscoveryService:
    """Collect scoped evidence and shape it for the parent agent."""

    def __init__(self, *, llm_client: OpenAICompatibleLLMClient | None = None) -> None:
        self.llm_client = llm_client

    def run(self, request: DiscoveryRequest) -> DiscoveryResponse:
        if request.objective_type is ObjectiveType.CODEBASE_DISCOVERY:
            response = self._run_codebase_discovery(request)
        elif request.objective_type is ObjectiveType.LOGS_TRIAGE:
            response = self._run_logs_triage(request)
        else:
            response = self._run_docs_research(request)

        if request.model_profile and self.llm_client:
            response = self._maybe_enrich_with_llm(request, response)
        return response

    def _run_codebase_discovery(self, request: DiscoveryRequest) -> DiscoveryResponse:
        documents = self._collect_documents(request)
        candidate_files = [
            CandidateFile(path=doc.path, reason="High keyword overlap with objective", score=round(doc.score, 2))
            for doc in documents[: request.max_files]
        ]
        candidate_symbols = self._extract_symbols(documents)
        snippets = self._build_snippets(documents, request)
        findings = [
            f"{Path(doc.path).name}: matched discovery terms with score {round(doc.score, 2)}"
            for doc in documents[: min(4, len(documents))]
        ]
        raw_reads = [item.path for item in candidate_files[: request.raw_read_budget]]
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
            confidence="medium" if candidate_files else "low",
        )

    def _run_logs_triage(self, request: DiscoveryRequest) -> DiscoveryResponse:
        command_results = run_allowed_commands(
            request.terminal_commands,
            request.command_allowlist_profile,
            cwd=self._first_real_path(request.scope_paths),
            max_commands=request.max_commands,
        )
        documents = self._collect_documents(request)
        findings = self._extract_error_findings(documents, command_results)
        candidate_files = [
            CandidateFile(path=doc.path, reason="Contains log/error evidence", score=round(doc.score, 2))
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
            CandidateFile(path=doc.path, reason="Relevant documentation hit", score=round(doc.score, 2))
            for doc in documents[: request.max_files]
        ]
        findings = []
        for doc in documents[: min(4, len(documents))]:
            heading = next((line.strip("# ").strip() for line in doc.text.splitlines() if line.startswith("#")), "")
            findings.append(f"{Path(doc.path).name}: {heading or 'top document candidate'}")
        raw_reads = [item.path for item in candidate_files[: request.raw_read_budget]]
        return DiscoveryResponse(
            summary=f"Collected {len(candidate_files)} documentation candidates for '{request.objective}'.",
            objective_type=request.objective_type,
            relevant_findings=findings or ["No documentation candidates found in scope."],
            candidate_files=candidate_files,
            candidate_symbols=[],
            small_snippets=self._build_snippets(documents, request) if request.return_snippets else [],
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
            if any(part in SKIP_DIR_NAMES for part in path.parts):
                continue
            if path.is_file() and path.suffix.lower() in TEXT_FILE_SUFFIXES:
                yield path

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
        path_lower = path.lower()
        text_lower = text.lower()
        score = 0.0
        for term in terms:
            score += path_lower.count(term) * 3
            score += text_lower.count(term)
        return score

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
            snippet = "\n".join(lines[start:end])[:400]
            if snippet.strip():
                snippets.append(
                    SmallSnippet(
                        path=doc.path,
                        snippet=snippet,
                        reason="Small raw excerpt around the first relevant match.",
                    )
                )
        return snippets

    def _extract_error_findings(self, documents: list[EvidenceDocument], command_results) -> list[str]:
        findings: list[str] = []
        for doc in documents:
            for line in doc.text.splitlines():
                if re.search(r"(error|exception|traceback|fail|timeout)", line, re.IGNORECASE):
                    findings.append(f"{Path(doc.path).name}: {line.strip()}")
                    if len(findings) >= 8:
                        return findings
        for result in command_results:
            combined = "\n".join(filter(None, [result.stdout, result.stderr]))
            for line in combined.splitlines():
                if re.search(r"(error|exception|traceback|fail|timeout)", line, re.IGNORECASE):
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

    def _maybe_enrich_with_llm(self, request: DiscoveryRequest, response: DiscoveryResponse) -> DiscoveryResponse:
        try:
            llm_json = self.llm_client.complete_json(
                request.model_profile,
                system_prompt=(
                    "You are a discovery subagent. Keep the output concise, evidence-driven, and never claim edits were made. "
                    "Return JSON with optional keys: summary, relevant_findings, recommended_next_action, confidence."
                ),
                user_prompt=(
                    f"Objective: {request.objective}\n"
                    f"Type: {request.objective_type.value}\n"
                    f"Existing summary: {response.summary}\n"
                    f"Relevant findings: {response.relevant_findings}\n"
                    f"Raw reads for parent: {response.raw_reads_needed_by_parent}\n"
                ),
            )
        except Exception:
            return response

        payload = response.model_dump()
        for key in ("summary", "recommended_next_action", "confidence"):
            if isinstance(llm_json.get(key), str) and llm_json[key]:
                payload[key] = llm_json[key]
        if isinstance(llm_json.get("relevant_findings"), list) and llm_json["relevant_findings"]:
            payload["relevant_findings"] = [str(item) for item in llm_json["relevant_findings"]]
        return DiscoveryResponse.model_validate(payload)
