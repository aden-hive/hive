"""Exit-code taxonomy + dispatch harness for the ``hive-tracker`` CLI.

Mirrors ``framework/crm/errors.py`` (the CRM CLI standard): commands raise
:class:`TrackerError` client-side, :func:`run` prints the result and translates
the failure to a stable exit code. Agents invoke the CLI through
``terminal_exec`` and always pass ``--json``, so they can branch on the exit
status without parsing stdout.

Exit codes 0/1/2/4/6 line up with ``hive-crm`` and ``hive-global-db``; 5 and 7
are tracker-specific (the registry gate and the SQL denylist).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

# Exit codes — the stable agent contract.
EXIT_OK = 0
EXIT_DOMAIN = 1  # sqlite error, or any unclassified domain failure
EXIT_NO_COLONY = 2  # no colony context — not running inside a colony
EXIT_PERMISSION = 3  # worker attempted a queen-only command
EXIT_NOT_FOUND = 4  # table / column does not exist
EXIT_NOT_REGISTERED = 5  # table exists but isn't whitelisted for worker writes
EXIT_VALIDATION = 6  # bad args, malformed JSON/CSV
EXIT_DENIED = 7  # SQL rejected by the tracker denylist
EXIT_PARTIAL = 9  # some rows written, some rejected — inspect `failed`
EXIT_BUSY = 10  # another writer holds the DB — retry


class TrackerError(Exception):
    """A classified CLI failure carrying its exit code and JSON error body."""

    def __init__(self, code: str, message: str, exit_code: int, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details

    def envelope(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        body.update(self.details)
        return {"ok": False, "error": body}


def validation(message: str, **details: Any) -> TrackerError:
    return TrackerError("validation", message, EXIT_VALIDATION, **details)


def not_found(message: str, **details: Any) -> TrackerError:
    return TrackerError("not_found", message, EXIT_NOT_FOUND, **details)


def not_registered(table: str, **details: Any) -> TrackerError:
    return TrackerError(
        "not_registered",
        (
            f"table {table!r} is not registered for worker writes. The queen must run "
            f"`hive-tracker register {table} --write-columns ... --key-columns ...` first."
        ),
        EXIT_NOT_REGISTERED,
        table=table,
        **details,
    )


def permission(message: str, **details: Any) -> TrackerError:
    return TrackerError("permission_denied", message, EXIT_PERMISSION, **details)


def denied(message: str, **details: Any) -> TrackerError:
    return TrackerError("denied", message, EXIT_DENIED, **details)


def domain(message: str, **details: Any) -> TrackerError:
    return TrackerError("domain_error", message, EXIT_DOMAIN, **details)


def busy(message: str, **details: Any) -> TrackerError:
    """Another process holds the write lock. Retryable, and distinct from every
    other failure — an agent should back off and re-run the SAME command, not
    edit it."""
    return TrackerError("busy", message, EXIT_BUSY, **details)


def from_sqlite(e: Exception, *, what: str) -> TrackerError:
    """Classify a raw sqlite failure.

    Every public op funnels through this. Without it a lock timeout escapes as a
    Python traceback on stderr with EMPTY stdout — and the agent contract is
    "always pass --json, branch on the exit code", so it would see neither an
    envelope nor a distinguishable code. Batches make this likely, not
    theoretical: the CLI holds the write lock for a whole transaction while
    converge() dispatches workers concurrently.
    """
    text = str(e)
    if "locked" in text.lower() or "busy" in text.lower():
        return busy(
            f"{what}: {text}. Another worker or the queen is writing to this tracker right now — wait a moment and re-run the same command.",
        )
    return domain(f"{what}: {text}")


def no_colony() -> TrackerError:
    """Raised when the process can't tell which colony it belongs to.

    The runtime stamps ``HIVE_TRACKER_DB`` / ``HIVE_COLONY_DIR`` into
    ``terminal_exec``'s environment for any agent bound to a colony, so this
    fires when the agent is not in a colony at all — never as a silent fallback
    onto some other colony's DB.
    """
    return TrackerError(
        "no_colony",
        (
            "no colony context — the tracker only exists inside a colony. The queen "
            "reaches colony mode by calling suggest_colony and waiting for the user to "
            "confirm the Create Colony popup; workers inherit it automatically. "
            "(Debug: pass --colony <name>.)"
        ),
        EXIT_NO_COLONY,
    )


def run(func: Callable[[], Any], *, as_json: bool, render: Callable[[Any], None]) -> None:
    """Invoke a command, print its result, and translate failures to exit codes."""
    try:
        result = func()
    except TrackerError as e:
        if as_json:
            print(json.dumps(e.envelope(), indent=2, default=str))
        else:
            print(f"error: {e.message}", file=sys.stderr)
        sys.exit(e.exit_code)

    if as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        render(result)
