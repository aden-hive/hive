"""Detect potentially destructive commands and surface a warning string.

Informational only — the warning is included in the exec envelope, not
used to block execution. Lets the agent re-read its command before
trusting the result of an irreversible action. Catalog ported from
claudecode's BashTool/destructiveCommandWarning.ts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Git — data loss / hard to reverse
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "may discard uncommitted changes"),
    (
        re.compile(r"\bgit\s+push\b[^;&|\n]*[ \t](--force|--force-with-lease|-f)\b"),
        "may overwrite remote history",
    ),
    (
        re.compile(r"\bgit\s+clean\b(?![^;&|\n]*(?:-[a-zA-Z]*n|--dry-run))[^;&|\n]*-[a-zA-Z]*f"),
        "may permanently delete untracked files",
    ),
    (re.compile(r"\bgit\s+checkout\s+(--\s+)?\.[ \t]*($|[;&|\n])"), "may discard all working tree changes"),
    (re.compile(r"\bgit\s+restore\s+(--\s+)?\.[ \t]*($|[;&|\n])"), "may discard all working tree changes"),
    (re.compile(r"\bgit\s+stash[ \t]+(drop|clear)\b"), "may permanently remove stashed changes"),
    (
        re.compile(r"\bgit\s+branch\s+(-D[ \t]|--delete\s+--force|--force\s+--delete)\b"),
        "may force-delete a branch",
    ),
    # Git — safety bypass
    (re.compile(r"\bgit\s+(commit|push|merge)\b[^;&|\n]*--no-verify\b"), "may skip safety hooks"),
    (re.compile(r"\bgit\s+commit\b[^;&|\n]*--amend\b"), "may rewrite the last commit"),
    # File deletion — most specific patterns first so the warning is descriptive
    (
        re.compile(r"(^|[;&|\n]\s*)rm\s+-[a-zA-Z]*[rR][a-zA-Z]*f|(^|[;&|\n]\s*)rm\s+-[a-zA-Z]*f[a-zA-Z]*[rR]"),
        "may recursively force-remove files",
    ),
    (re.compile(r"(^|[;&|\n]\s*)rm\s+-[a-zA-Z]*[rR]"), "may recursively remove files"),
    (re.compile(r"(^|[;&|\n]\s*)rm\s+-[a-zA-Z]*f"), "may force-remove files"),
    # Database
    (
        re.compile(r"\b(DROP|TRUNCATE)\s+(TABLE|DATABASE|SCHEMA)\b", re.IGNORECASE),
        "may drop or truncate database objects",
    ),
    (re.compile(r"\bDELETE\s+FROM\s+\w+[ \t]*(;|\"|'|\n|$)", re.IGNORECASE), "may delete rows from a database table"),
    # Infrastructure
    (re.compile(r"\bkubectl\s+delete\b"), "may delete Kubernetes resources"),
    (re.compile(r"\bterraform\s+destroy\b"), "may destroy Terraform infrastructure"),
)


def get_warning(command: str | Sequence[str]) -> str | None:
    """Return a warning string if the command matches a destructive pattern.

    For argv-style invocations (``command=["rm", "-rf", "/tmp/x"]``), we
    join with spaces so the same regex catalog applies. Returns None
    when nothing matches.
    """
    if isinstance(command, (list, tuple)):
        text = " ".join(str(c) for c in command)
    else:
        text = command

    for pattern, message in _PATTERNS:
        if pattern.search(text):
            return message
    return None


__all__ = ["get_warning"]
