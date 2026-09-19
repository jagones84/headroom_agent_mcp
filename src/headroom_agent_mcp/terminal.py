"""Safe command policy and execution helpers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .models import CommandAllowlistProfile, CommandResult


READONLY_PREFIXES = {
    ("git", "status"),
    ("git", "diff", "--name-only"),
    ("ls",),
    ("dir",),
    ("find",),
    ("grep",),
    ("head",),
    ("tail",),
    ("cat",),
}

TERMINAL_ONLY_PREFIXES = {
    ("pytest", "-q"),
    ("npm", "test"),
    ("pnpm", "test"),
    ("uv", "run", "pytest"),
}

FIND_DANGEROUS_TOKENS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprintf", "-fprint"}
SCOPED_READ_COMMANDS = {"ls", "dir", "find", "cat", "head", "tail", "grep"}


def is_command_allowed(command: list[str], profile: CommandAllowlistProfile) -> bool:
    if not command:
        return False
    prefixes = set(READONLY_PREFIXES)
    if profile is CommandAllowlistProfile.SAFE_TERMINAL:
        prefixes.update(TERMINAL_ONLY_PREFIXES)
    return any(tuple(command[: len(prefix)]) == prefix for prefix in prefixes)


def is_command_allowed_by_profile(command: list[str], allowed_commands: list[list[str]] | None) -> bool:
    if allowed_commands is None:
        return True
    return any(tuple(command[: len(prefix)]) == tuple(prefix) for prefix in allowed_commands)


def _path_within_scope(raw_path: str, scope_root: Path) -> bool:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = scope_root / candidate
    try:
        candidate.resolve(strict=False).relative_to(scope_root)
    except ValueError:
        return False
    return True


def _validate_command(
    command: list[str],
    profile: CommandAllowlistProfile,
    scope_root: Path | None,
    allowed_commands: list[list[str]] | None,
) -> str | None:
    if not is_command_allowed(command, profile):
        return "Blocked by policy: command prefix is not allowlisted."
    if not is_command_allowed_by_profile(command, allowed_commands):
        return "Blocked by policy: command is not allowed by the active profile configuration."
    if not command:
        return "Blocked by policy: empty command."

    command_name = command[0]
    if command_name == "find" and any(token in FIND_DANGEROUS_TOKENS for token in command[1:]):
        return "Blocked by policy: dangerous find action is not allowed."

    if scope_root is None or command_name not in SCOPED_READ_COMMANDS:
        return None

    for token in command[1:]:
        if not token or token.startswith("-") or token in {".", "{}","+"}:
            continue
        if command_name == "grep" and token == command[1]:
            continue
        if token.startswith(("http://", "https://")):
            continue
        if not _path_within_scope(token, scope_root):
            return f"Blocked by policy: path '{token}' is outside the allowed scope."
    return None


def run_allowed_commands(
    commands: list[list[str]],
    profile: CommandAllowlistProfile,
    *,
    cwd: str | Path | None = None,
    max_commands: int,
    allowed_commands: list[list[str]] | None = None,
) -> list[CommandResult]:
    results: list[CommandResult] = []
    scope_root = Path(cwd).resolve(strict=False) if cwd else None
    for command in commands[:max_commands]:
        validation_error = _validate_command(command, profile, scope_root, allowed_commands)
        if validation_error:
            results.append(
                CommandResult(
                    command=command,
                    exit_code=-1,
                    stdout="",
                    stderr=validation_error,
                    blocked=True,
                )
            )
            continue
        completed = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        results.append(
            CommandResult(
                command=command,
                exit_code=completed.returncode,
                stdout=completed.stdout[-4000:],
                stderr=completed.stderr[-2000:],
            )
        )
    return results
