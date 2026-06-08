"""Write every LLM turn to ~/.hive/llm_logs/<ts>.jsonl for replay/debugging.

Two record kinds, distinguished by ``_kind``:

* ``session_header`` — emitted on the first turn of an ``execution_id`` and
  any time its ``system_prompt`` or ``tools`` change. Carries those large
  fields once instead of per-turn.
* ``turn`` — one per LLM call. Carries per-turn outputs plus a
  content-addressed message delta: ``message_hashes`` is the full ordered
  message sequence for this turn, ``new_messages`` is hash → body for
  messages we haven't emitted before for this ``execution_id``. The reader
  reassembles full ``messages`` by accumulating ``new_messages`` across
  prior turn records. Content-addressed (not positional) because the agent
  prunes messages mid-session — a tail-delta would be wrong.

Errors are silently swallowed — this must never break the agent.
"""

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)


def _llm_debug_dir() -> Path:
    """Resolve $HIVE_HOME/llm_logs lazily so the env override (set by the
    desktop) takes effect. A module-level constant would freeze whatever
    HIVE_HOME was at import time and miss late-bound test overrides."""
    from framework.config import HIVE_HOME

    return HIVE_HOME / "llm_logs"


_log_file: IO[str] | None = None
_log_ready = False  # lazy init guard

# Per-execution_id delta state. Reset implicitly on process restart — a fresh
# log file has no prior context, so re-emitting the header on first turn is
# correct.
_session_header_hash: dict[str, str] = {}
_session_seen_msgs: dict[str, set[str]] = {}


def _open_log() -> IO[str] | None:
    """Open the JSONL log file for this process."""
    debug_dir = _llm_debug_dir()
    debug_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = debug_dir / f"{ts}.jsonl"
    logger.info("LLM debug log → %s", path)
    return open(path, "a", encoding="utf-8")  # noqa: SIM115


def _serialize_tools(tools: Any) -> list[dict[str, Any]]:
    """Reduce a list of Tool dataclasses to the schema fields shown to the LLM.

    Best-effort: unknown shapes fall back to ``str()`` so logging never raises.
    """
    if not tools:
        return []
    out: list[dict[str, Any]] = []
    for tool in tools:
        try:
            out.append(
                {
                    "name": getattr(tool, "name", ""),
                    "description": getattr(tool, "description", ""),
                    "parameters": getattr(tool, "parameters", {}) or {},
                }
            )
        except Exception:
            out.append({"name": str(tool)})
    return out


def _content_hash(payload: Any) -> str:
    raw = json.dumps(payload, default=str, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _write_line(record: dict[str, Any]) -> None:
    assert _log_file is not None
    _log_file.write(json.dumps(record, default=str) + "\n")
    _log_file.flush()


def log_llm_turn(
    *,
    node_id: str,
    stream_id: str,
    execution_id: str,
    iteration: int,
    system_prompt: str,
    messages: list[dict[str, Any]],
    assistant_text: str,
    tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    token_counts: dict[str, Any],
    tools: list[Any] | None = None,
) -> None:
    """Write JSONL records capturing one LLM turn (header + turn delta).

    Never raises.
    """
    try:
        # Skip logging during test runs to avoid polluting real logs.
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("HIVE_DISABLE_LLM_LOGS"):
            return
        global _log_file, _log_ready  # noqa: PLW0603
        if not _log_ready:
            _log_file = _open_log()
            _log_ready = True
        if _log_file is None:
            return

        # UTC + offset matches tool_call start_timestamp (agent_loop.py)
        # so the viewer can render every event in one consistent local zone.
        timestamp = datetime.now(UTC).isoformat()
        serialized_tools = _serialize_tools(tools)

        # Re-emit the header on first turn or whenever system/tools change.
        # The Queen reflects different prompts across turns, so we can't
        # assume strict immutability per execution_id.
        header_hash = _content_hash({"system_prompt": system_prompt, "tools": serialized_tools})
        if _session_header_hash.get(execution_id) != header_hash:
            _write_line(
                {
                    "_kind": "session_header",
                    "timestamp": timestamp,
                    "execution_id": execution_id,
                    "node_id": node_id,
                    "stream_id": stream_id,
                    "header_hash": header_hash,
                    "system_prompt": system_prompt,
                    "tools": serialized_tools,
                }
            )
            _session_header_hash[execution_id] = header_hash

        seen = _session_seen_msgs.setdefault(execution_id, set())
        message_hashes: list[str] = []
        new_messages: dict[str, dict[str, Any]] = {}
        for msg in messages or []:
            h = _content_hash(msg)
            message_hashes.append(h)
            if h not in seen:
                seen.add(h)
                new_messages[h] = msg

        _write_line(
            {
                "_kind": "turn",
                "timestamp": timestamp,
                "execution_id": execution_id,
                "node_id": node_id,
                "stream_id": stream_id,
                "iteration": iteration,
                "header_hash": header_hash,
                "message_hashes": message_hashes,
                "new_messages": new_messages,
                "assistant_text": assistant_text,
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "token_counts": token_counts,
            }
        )
    except Exception:
        pass  # never break the agent
