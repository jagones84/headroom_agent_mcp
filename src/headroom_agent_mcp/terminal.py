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


def is_command_allowed(command: list[str], profile: CommandAllowlistProfile) -> bool:
    if not command:
        return False
    prefixes = set(READONLY_PREFIXES)
    if profile is CommandAllowlistProfile.SAFE_TERMINAL:
        prefixes.update(TERMINAL_ONLY_PREFIXES)
    return any(tuple(command[: len(prefix)]) == prefix for prefix in prefixes)


def run_allowed_commands(
    commands: list[list[str]],
    profile: CommandAllowlistProfile,
    *,
    cwd: str | Path | None = None,
    max_commands: int,
) -> list[CommandResult]:
    results: list[CommandResult] = []
    for command in commands[:max_commands]:
        if not is_command_allowed(command, profile):
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
