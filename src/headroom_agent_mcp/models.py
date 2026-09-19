"""Pydantic models for the discovery MCP contract."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ObjectiveType(str, Enum):
    DOCS_RESEARCH = "docs_research"
    LOGS_TRIAGE = "logs_triage"
    CODEBASE_DISCOVERY = "codebase_discovery"


class CommandAllowlistProfile(str, Enum):
    SAFE_READONLY = "safe_readonly"
    SAFE_TERMINAL = "safe_terminal"


class CandidateFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    reason: str
    score: float = Field(ge=0.0)


class CandidateSymbol(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    path: str
    kind: str
    reason: str


class SmallSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    snippet: str
    reason: str


class CommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str]
    exit_code: int
    stdout: str
    stderr: str
    blocked: bool = False


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    objective: str = Field(min_length=1)
    objective_type: ObjectiveType
    scope_paths: list[str] = Field(default_factory=list)
    query_hints: list[str] = Field(default_factory=list)
    terminal_commands: list[list[str]] = Field(default_factory=list)
    command_allowlist_profile: CommandAllowlistProfile = CommandAllowlistProfile.SAFE_READONLY
    max_files: int = Field(default=8, ge=1, le=50)
    max_commands: int = Field(default=4, ge=0, le=20)
    return_snippets: bool = True
    raw_read_budget: int = Field(default=4, ge=1, le=20)
    model_profile: str | None = None

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("objective must not be blank")
        return value


class DiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    objective_type: ObjectiveType
    relevant_findings: list[str]
    candidate_files: list[CandidateFile]
    candidate_symbols: list[CandidateSymbol]
    small_snippets: list[SmallSnippet]
    commands_run: list[CommandResult]
    raw_reads_needed_by_parent: list[str]
    uncertainties: list[str]
    recommended_next_action: str
    confidence: str
    llm_enriched: bool = False
    llm_error: str | None = None
    llm_profile_used: str | None = None
