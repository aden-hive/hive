"""Helpers to build the standard exec/job envelope with truncation.

The envelope shape is documented in the foundational skill — keep
this module's output stable so skill updates don't have to chase
field renames. Callers pass raw bytes; we decode and trim.
"""

from __future__ import annotations

from collections.abc import Sequence

from terminal_tools.common.destructive_warning import get_warning
from terminal_tools.common.output_store import get_store
from terminal_tools.common.semantic_exit import classify


def _truncate_bytes(buf: bytes, max_bytes: int) -> tuple[str, int, str]:
    """Trim ``buf`` to ``max_bytes`` (decoded). Returns
    ``(decoded_text, dropped_bytes, full_for_handle)``. We always store
    the *original* bytes in the handle so the agent gets exactly what
    the process emitted, even when truncation point split a multi-byte
    char.
    """
    if max_bytes < 0:
        max_bytes = 0
    if len(buf) <= max_bytes:
        return buf.decode("utf-8", errors="replace"), 0, buf.decode("utf-8", errors="replace")

    head = buf[:max_bytes]
    return (
        head.decode("utf-8", errors="replace"),
        len(buf) - max_bytes,
        buf.decode("utf-8", errors="replace"),
    )


def build_exec_envelope(
    *,
    command: str | Sequence[str],
    exit_code: int | None,
    stdout_bytes: bytes,
    stderr_bytes: bytes,
    runtime_ms: int,
    pid: int | None,
    timed_out: bool,
    signaled: bool = False,
    max_output_kb: int = 256,
    auto_backgrounded: bool = False,
    job_id: str | None = None,
    auto_shell: bool = False,
) -> dict:
    """Construct the standard exec envelope.

    See ``terminal-tools-foundations`` SKILL for the field semantics. The
    inline ``stdout``/``stderr`` are decoded and trimmed; if either
    overflows ``max_output_kb`` the *full* bytes are stashed in the
    output store under ``output_handle`` for retrieval via
    ``terminal_output_get``. Both streams share the same handle (with
    ``out_<hex>:stdout`` / ``out_<hex>:stderr`` suffixes) when both
    overflow — the agent uses the suffix to pick a stream.
    """
    max_bytes = max(1024, max_output_kb * 1024)

    stdout_text, stdout_dropped, stdout_full = _truncate_bytes(stdout_bytes, max_bytes)
    stderr_text, stderr_dropped, stderr_full = _truncate_bytes(stderr_bytes, max_bytes)

    output_handle: str | None = None
    if stdout_dropped > 0 or stderr_dropped > 0:
        store = get_store()
        # Stash whichever overflowed (or both, joined with a separator
        # the foundational skill documents). For simplicity we always
        # store both when either overflows so the agent can fetch the
        # other stream in full too if it wants.
        combined = b"--- stdout ---\n" + stdout_bytes + b"\n--- stderr ---\n" + stderr_bytes
        output_handle = store.put(combined)

    semantic_status, semantic_message = classify(command, exit_code, timed_out=timed_out, signaled=signaled)

    warning = get_warning(command)

    return {
        "exit_code": exit_code,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "stdout_truncated_bytes": stdout_dropped,
        "stderr_truncated_bytes": stderr_dropped,
        "runtime_ms": int(runtime_ms),
        "pid": int(pid) if pid is not None else None,
        "output_handle": output_handle,
        "timed_out": bool(timed_out),
        "semantic_status": semantic_status,
        "semantic_message": semantic_message,
        "warning": warning,
        "auto_backgrounded": bool(auto_backgrounded),
        "job_id": job_id,
        "auto_shell": bool(auto_shell),
    }


__all__ = ["build_exec_envelope"]
