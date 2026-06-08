"""Sidecar summary cache for cold-session listings.

Each queen session directory grows a ``summary.json`` file that mirrors the
expensive-to-recompute fields surfaced by ``SessionManager.list_cold_sessions``:
``message_count``, ``last_message`` snippet, and ``last_active_at``.

Without this cache the queen-history sidebar reads **every** part file of
**every** session on the disk for each list request. That cost grows with
total messages across all sessions, not just the one being opened, and is
visible whenever the user navigates to the session list.

Update path: ``FileConversationStore.write_part`` calls ``update_summary``
after each successful part write — best-effort, never blocks the caller on
failure.

Read path: ``list_cold_sessions`` reads ``summary.json`` and only falls back
to a full part scan when the file is missing or stale (parts dir mtime newer
than the summary). The rebuild path also writes a fresh summary, so the
slow path is paid at most once per session per upgrade.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

_SUMMARY_FILENAME = "summary.json"
_LAST_MESSAGE_MAX_CHARS = 120


def is_client_facing(part: dict[str, Any]) -> bool:
    """Whether this part appears in the client-visible chat list.

    Mirrors the predicate in ``SessionManager.list_cold_sessions`` so the
    cached counts agree with a full rebuild.
    """
    if part.get("is_transition_marker"):
        return False
    role = part.get("role")
    if role == "tool":
        return False
    if role == "assistant" and part.get("tool_calls"):
        return False
    return True


def _extract_text(content: Any) -> str:
    """Render a part's ``content`` field as a flat string for the snippet."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        # Anthropic-style content blocks: [{"type": "text", "text": "..."}]
        return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _summary_path(session_dir: Path) -> Path:
    return session_dir / _SUMMARY_FILENAME


def read_summary(session_dir: Path) -> dict | None:
    """Return the cached summary dict, or ``None`` if missing/corrupt."""
    path = _summary_path(session_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def is_stale(session_dir: Path) -> bool:
    """True when the summary is missing or older than the latest part write.

    Compares ``summary.json`` mtime against ``conversations/parts/`` (and
    any node-based ``conversations/<node>/parts/``) directory mtime.
    POSIX dir mtime updates whenever entries are added, so a new part flush
    bumps the parts-dir mtime above the summary's.
    """
    summary_path = _summary_path(session_dir)
    if not summary_path.exists():
        return True
    try:
        summary_mtime = summary_path.stat().st_mtime
    except OSError:
        return True

    convs_dir = session_dir / "conversations"
    if not convs_dir.exists():
        return False

    candidate_dirs: list[Path] = [convs_dir / "parts"]
    try:
        for child in convs_dir.iterdir():
            if child.is_dir() and child.name != "parts":
                candidate_dirs.append(child / "parts")
    except OSError:
        return False

    for d in candidate_dirs:
        if not d.exists():
            continue
        try:
            if d.stat().st_mtime > summary_mtime + 0.001:
                return True
        except OSError:
            continue
    return False


def _write_summary(session_dir: Path, data: dict) -> None:
    path = _summary_path(session_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with atomic_write(path) as f:
            json.dump(data, f)
    except OSError:
        logger.debug("session_summary: failed to write %s", path, exc_info=True)


def update_summary(session_dir: Path, part: dict[str, Any]) -> None:
    """Incrementally fold ``part`` into the cached summary.

    Best-effort; swallows errors so the part-write path is never broken by
    a summary failure. Reads the prior summary, mutates a few fields, and
    writes back atomically.

    Only client-facing parts (see :func:`is_client_facing`) bump the count
    and the ``last_message`` snippet — tool calls and transition markers
    are persisted but not surfaced in the sidebar.
    """
    try:
        if not is_client_facing(part):
            return

        existing = read_summary(session_dir) or {}
        message_count = int(existing.get("message_count") or 0) + 1
        last_active_at = float(existing.get("last_active_at") or 0.0)
        last_message = existing.get("last_message")

        # Prefer an explicit timestamp on the part; fall back to the current
        # summary's most-recent activity. Parts also carry ``seq`` which is
        # monotonic per-session, but seq is not a wall-clock — keep both.
        part_ts = part.get("created_at")
        if isinstance(part_ts, (int, float)) and part_ts > last_active_at:
            last_active_at = float(part_ts)

        # Update the snippet with the latest assistant message; user messages
        # don't replace it, matching the existing list_cold_sessions behavior
        # (it scans backward for the last assistant message).
        if part.get("role") == "assistant":
            text = _extract_text(part.get("content")).strip()
            if text:
                last_message = text[:_LAST_MESSAGE_MAX_CHARS]

        last_part_seq = part.get("seq")
        if last_part_seq is None:
            last_part_seq = existing.get("last_part_seq")

        _write_summary(
            session_dir,
            {
                "message_count": message_count,
                "last_message": last_message,
                "last_active_at": last_active_at,
                "last_part_seq": last_part_seq,
            },
        )
    except Exception:
        logger.debug("session_summary: update_summary failed", exc_info=True)


def rebuild_summary(session_dir: Path) -> dict | None:
    """Full-scan rebuild — reads every part file and recomputes the summary.

    Returns the rebuilt dict and writes it to ``summary.json``. Returns
    ``None`` when the conversations directory is absent (no parts yet).

    Used by ``list_cold_sessions`` as the migration / fallback path when
    the cache is missing or stale.
    """
    convs_dir = session_dir / "conversations"
    if not convs_dir.exists():
        return None

    all_parts: list[dict] = []

    def _collect(parts_dir: Path) -> None:
        if not parts_dir.exists():
            return
        try:
            for part_file in sorted(parts_dir.iterdir()):
                if part_file.suffix != ".json":
                    continue
                try:
                    part = json.loads(part_file.read_text(encoding="utf-8"))
                    part.setdefault("created_at", part_file.stat().st_mtime)
                    all_parts.append(part)
                except (json.JSONDecodeError, OSError):
                    continue
        except OSError:
            return

    _collect(convs_dir / "parts")
    try:
        for node_dir in convs_dir.iterdir():
            if node_dir.is_dir() and node_dir.name != "parts":
                _collect(node_dir / "parts")
    except OSError:
        pass

    client_msgs = [p for p in all_parts if is_client_facing(p)]
    client_msgs.sort(key=lambda m: m.get("created_at", m.get("seq", 0)))

    last_active_at = 0.0
    last_message: str | None = None
    if client_msgs:
        latest_ts = client_msgs[-1].get("created_at")
        if isinstance(latest_ts, (int, float)):
            last_active_at = float(latest_ts)
        for msg in reversed(client_msgs):
            if msg.get("role") != "assistant":
                continue
            text = _extract_text(msg.get("content")).strip()
            if text:
                last_message = text[:_LAST_MESSAGE_MAX_CHARS]
                break

    last_part_seq = None
    if all_parts:
        seqs = [p.get("seq") for p in all_parts if isinstance(p.get("seq"), int)]
        if seqs:
            last_part_seq = max(seqs)

    summary = {
        "message_count": len(client_msgs),
        "last_message": last_message,
        "last_active_at": last_active_at,
        "last_part_seq": last_part_seq,
    }
    _write_summary(session_dir, summary)
    return summary
