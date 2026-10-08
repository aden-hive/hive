"""Per-command exit-code semantics.

Many commands use exit codes to convey information other than just
success/failure. ``grep`` returns 1 when no matches are found, which
is not an error. Encoding this lookup means the agent reads
``semantic_status`` instead of having to memorize per-command quirks.

Catalog ported from claudecode's BashTool/commandSemantics.ts. We
inspect only the *final* command in a piped chain (its exit code is
what the shell propagates), and only when the command is run with
``shell=False`` (i.e. we know the argv). For ``shell=True`` we fall
back to default semantics — the heuristic of parsing a bash command
string for "the last command" is fragile and the upstream tool
already documents the issue.
"""

from __future__ import annotations

from collections.abc import Sequence

SemanticStatus = str  # "ok" | "signal" | "error"


# Maps base command name → (exit_code → semantic). Returning
# (status, message) — message may be None for the success cases.
_SEMANTICS: dict[str, dict[int, tuple[SemanticStatus, str | None]]] = {
    # grep: 0=matches, 1=no matches (not an error), 2+=error
    "grep": {0: ("ok", None), 1: ("ok", "No matches found")},
    "rg": {0: ("ok", None), 1: ("ok", "No matches found")},
    "ripgrep": {0: ("ok", None), 1: ("ok", "No matches found")},
    # find: 0=success, 1=partial (some dirs unreadable), 2+=error
    "find": {0: ("ok", None), 1: ("ok", "Some directories were inaccessible")},
    # diff: 0=identical, 1=differ (informational), 2+=error
    "diff": {0: ("ok", None), 1: ("ok", "Files differ")},
    # test / [: 0=true, 1=false, 2+=error
    "test": {0: ("ok", None), 1: ("ok", "Condition is false")},
    "[": {0: ("ok", None), 1: ("ok", "Condition is false")},
}


def _base_command(command: str | Sequence[str]) -> str:
    """Extract the base command (first word) from argv or a string.

    For shell=True strings, picks the *last* command in a pipeline since
    that determines the propagated exit code. Heuristic and intentionally
    not security-critical — only used to label the exit-code semantics.
    """
    if isinstance(command, (list, tuple)):
        return command[0] if command else ""

    if not isinstance(command, str):
        return ""

    # Take the segment after the last unquoted pipe/&&/||/; — best-effort.
    text = command
    for sep in ("||", "&&", "|", ";"):
        # Crude split — fine for the heuristic.
        if sep in text:
            text = text.split(sep)[-1]

    text = text.strip()
    if not text:
        return ""
    first = text.split()[0]
    # Strip a leading path: /usr/bin/grep → grep
    return first.rsplit("/", 1)[-1]


def classify(
    command: str | Sequence[str],
    exit_code: int | None,
    *,
    timed_out: bool = False,
    signaled: bool = False,
) -> tuple[SemanticStatus, str | None]:
    """Classify an exit code with command-specific semantics.

    Returns (status, message) where status is one of "ok"/"signal"/"error"
    and message is a short explanation when the status would otherwise
    surprise the agent (e.g. ``grep`` exiting 1).
    """
    if timed_out:
        return ("error", "Command timed out")
    if signaled:
        return ("signal", f"Killed by signal (exit {exit_code})")
    if exit_code is None:
        return ("ok", "Still running")  # auto-backgrounded case

    base = _base_command(command)
    table = _SEMANTICS.get(base)
    if table is not None:
        if exit_code in table:
            return table[exit_code]
        # Beyond the catalog's known codes for this command, treat as error.
        return ("error", f"Command failed with exit code {exit_code}")

    # Default: zero is success, nonzero is error.
    if exit_code == 0:
        return ("ok", None)
    return ("error", f"Command failed with exit code {exit_code}")


__all__ = ["classify"]
