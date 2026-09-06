"""Detect potentially destructive commands and surface a warning string.

Informational only — the warning is included in the exec envelope, not
used to block execution. Lets the agent re-read its command before
trusting the result of an irreversible action. Catalog ported from
claudecode's BashTool/destructiveCommandWarning.ts.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Switch/flag lookaheads, scoped to the current command segment. The segment
# body excludes separators *and* both newline characters, and the whitespace
# before the flag is horizontal only — a bare ``\s`` would consume the newline
# the segment body just refused, letting ``Remove-Item C:\x\n-Recurse`` match
# as one command.
_SEG = r"[^;&|\r\n]*[ \t]"

# PowerShell binds a parameter by any unique prefix of its name, so the switch
# names are spelled as prefix alternations rather than ``-rec\w*``: a trailing
# ``\w*`` would also match ``-recurseTypo``, which PowerShell rejects outright,
# and warning about a command that never runs is noise.
_RECURSE_NAME = r"rec(?:u(?:r(?:s(?:e)?)?)?)?"
_FORCE_NAME = r"for(?:c(?:e)?)?"

# A PowerShell switch can be explicitly disabled as ``-Recurse:$false``, which
# is not destructive, so that spelling is rejected. ``\b`` keeps the rejection
# to the literal value: ``-Recurse:$falseFlag`` is a *variable* that may resolve
# to true, so it must still warn.
_PS_RECURSE = rf"(?={_SEG}-{_RECURSE_NAME}\b(?![ \t]*:[ \t]*\$false\b))"
_PS_FORCE = rf"(?={_SEG}-{_FORCE_NAME}\b(?![ \t]*:[ \t]*\$false\b))"

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
    # File deletion — Windows cmd and PowerShell. On a Windows host the
    # resolved shell may be PowerShell or cmd, so the POSIX ``rm`` patterns
    # above leave a platform-shaped hole — the same reasoning ``command_guard``
    # applies to its Windows kill/launch verbs. The cmd verbs are matched only
    # in command position because ``del``/``rd`` are short, word-like tokens;
    # ``Remove-Item`` is unambiguous and is matched anywhere in a pipeline.
    (
        re.compile(rf"(^|[;&|\n]\s*)(?:del|erase)\b(?={_SEG}/s\b)(?={_SEG}/[fq]\b)", re.IGNORECASE),
        "may recursively force-delete files",
    ),
    (
        re.compile(rf"(^|[;&|\n]\s*)(?:del|erase)\b(?={_SEG}/s\b)", re.IGNORECASE),
        "may recursively delete files",
    ),
    (
        re.compile(rf"(^|[;&|\n]\s*)(?:del|erase)\b(?={_SEG}/[fq]\b)", re.IGNORECASE),
        "may force-delete files",
    ),
    (
        re.compile(rf"(^|[;&|\n]\s*)(?:rd|rmdir)\b(?={_SEG}/s\b)", re.IGNORECASE),
        "may recursively delete a directory tree",
    ),
    (
        re.compile(rf"\bremove-item\b{_PS_RECURSE}{_PS_FORCE}", re.IGNORECASE),
        "may recursively force-delete files",
    ),
    (re.compile(rf"\bremove-item\b{_PS_RECURSE}", re.IGNORECASE), "may recursively delete files"),
    (re.compile(rf"\bremove-item\b{_PS_FORCE}", re.IGNORECASE), "may force-delete files"),
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
