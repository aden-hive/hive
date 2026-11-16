"""Fork a queen DM session at a point in its conversation.

A fork is a new session directory beside the source holding the source's
history up to the cut: the conversation parts the model reads, the event log
the UI replays, and the session's files (attachments, spilled tool results)
the history refers to. The task plan starts empty. The fork opens like any
history session: cold-resumed, parked waiting for the user.

Cuts sit on user messages, where the event log and the conversation line up
exactly: a ``client_input_received`` event and its ``client_input_committed``,
which records the message's conversation seq. ``before_input_at`` names a user
message by its event timestamp and cuts just before it; without it the whole
session is copied.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# meta.json flags that describe the source's own fate, not the conversation.
_SOURCE_ONLY_META = ("colony_spawned", "spawned_colony_id", "superseded_by", "colony_fork")
# Session files a fork starts without: the task plan, caches rebuilt on
# demand, the reminder ticker's state, and the memory timeline (its items stay
# in the source; see ``timeline.mark_extracted``).
_NOT_CARRIED = {"tasks.json", "summary.json", "reminder_state.json", "timeline.jsonl", "timeline_meta.json"}
# How a session that finished its turn is parked, as the agent loop writes it.
_PARKED_ON_USER = {
    "questions": None,
    "colony_suggestion": None,
    "colony_pivot": None,
    "credential_form": None,
    "emit_client_request": True,
    "reason": "turn_done",
}


class ForkError(ValueError):
    """The requested fork point can't be honoured."""


@dataclass(frozen=True)
class _Cut:
    # Event-log lines kept: [:event_index]. None keeps them all.
    event_index: int | None
    # Conversation parts kept: seq < seq. None keeps them all.
    seq: int | None


def _parse(line: str) -> dict[str, Any]:
    try:
        event = json.loads(line)
    except ValueError:
        return {}
    return event if isinstance(event, dict) else {}


def _find_cut(events: list[dict[str, Any]], before_input_at: str | None) -> _Cut:
    if before_input_at is None:
        return _Cut(event_index=None, seq=None)
    for i, event in enumerate(events):
        if event.get("type") != "client_input_received" or event.get("timestamp") != before_input_at:
            continue
        correlation = event.get("correlation_id")
        for later in events[i + 1 :]:
            if later.get("type") != "client_input_committed":
                continue
            # Older logs carry no correlation ids; the next commit is this one.
            if correlation and later.get("correlation_id") != correlation:
                continue
            seq = (later.get("data") or {}).get("seq")
            if isinstance(seq, int):
                return _Cut(event_index=i, seq=seq)
            break
        raise ForkError("That message never reached the conversation (it was still queued); fork from an earlier one.")
    raise ForkError(f"No message sent at {before_input_at} in this session.")


def _part_seq(path: Path) -> int | None:
    try:
        return int(path.stem)
    except ValueError:
        return None


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)


def fork_session_dir(src: Path, new_session_id: str, *, before_input_at: str | None = None) -> Path:
    """Copy ``src`` into a sibling session ``new_session_id``, cut before the
    user message sent at ``before_input_at`` (or whole). Returns the new dir.

    Raises:
        ForkError: ``before_input_at`` names no committed message here, or a
            point the conversation has since compacted away.
    """
    log_path = src / "events.jsonl"
    lines = log_path.read_text(encoding="utf-8").splitlines(keepends=True) if log_path.exists() else []
    cut = _find_cut([_parse(line) for line in lines], before_input_at)

    parts_dir = src / "conversations" / "parts"
    if cut.seq is not None and not (parts_dir / f"{cut.seq:010d}.json").exists():
        raise ForkError("That point is before this conversation was compacted; fork from a later message.")

    dst = src.parent / new_session_id
    dst.mkdir()
    try:
        _write_conversation(src / "conversations", dst / "conversations", cut)
        kept = lines if cut.event_index is None else lines[: cut.event_index]
        (dst / "events.jsonl").write_text("".join(kept), encoding="utf-8")
        for entry in src.iterdir():
            if entry.name in ("conversations", "events.jsonl", "meta.json") or entry.name in _NOT_CARRIED:
                continue
            _copy(entry, dst / entry.name)
        _write_meta(src, dst, before_input_at)
    except BaseException:
        shutil.rmtree(dst, ignore_errors=True)
        raise
    return dst


def _write_conversation(src: Path, dst: Path, cut: _Cut) -> None:
    (dst / "parts").mkdir(parents=True)
    last_seq = -1
    for part in (src / "parts").glob("*.json"):
        seq = _part_seq(part)
        if seq is None or (cut.seq is not None and seq >= cut.seq):
            continue
        shutil.copy2(part, dst / "parts" / part.name)
        last_seq = max(last_seq, seq)
    for entry in src.iterdir():
        # In-flight streaming state belongs to the source's live turn.
        if entry.name in ("parts", "partials", "cursor.json"):
            continue
        _copy(entry, dst / entry.name)

    try:
        cursor = json.loads((src / "cursor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cursor = {}
    cursor.update(
        next_seq=cut.seq if cut.seq is not None else max(cursor.get("next_seq") or 0, last_seq + 1),
        # The fork waits for the user, as after any finished turn; without
        # this a resume would start the queen talking on its own.
        pending_input=dict(_PARKED_ON_USER),
        recent_responses=[],
        recent_tool_fingerprints=[],
        user_stopped=False,
    )
    (dst / "cursor.json").write_text(json.dumps(cursor, ensure_ascii=False), encoding="utf-8")


def _write_meta(src: Path, dst: Path, before_input_at: str | None) -> None:
    from framework.agents.queen import timeline

    try:
        meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        meta = {}
    for key in _SOURCE_ONLY_META:
        meta.pop(key, None)
    meta["created_at"] = time.time()
    # The title carries over as is; ``forked_from`` is what marks a fork.
    meta["forked_from"] = {"session_id": src.name, "before_input_at": before_input_at}
    (dst / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    timeline.mark_extracted(dst)
