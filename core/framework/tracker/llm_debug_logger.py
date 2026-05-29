"""Write every LLM turn to ~/.hive/llm_logs/<ts>.jsonl for replay/debugging.

Each line is a JSON object with the full LLM turn: the request payload
(system prompt + messages), assistant text, tool calls, tool results, and
token counts. The file is opened lazily on first call and flushed after every
write. Errors are silently swallowed — this must never break the agent.
"""

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
    """Write one JSONL line capturing a complete LLM turn.

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
        record = {
            # UTC + offset matches tool_call start_timestamp (agent_loop.py)
            # so the viewer can render every event in one consistent local zone.
            "timestamp": datetime.now(UTC).isoformat(),
            "node_id": node_id,
            "stream_id": stream_id,
            "execution_id": execution_id,
            "iteration": iteration,
            "system_prompt": system_prompt,
            "tools": _serialize_tools(tools),
            "messages": messages,
            "assistant_text": assistant_text,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
            "token_counts": token_counts,
        }
        _log_file.write(json.dumps(record, default=str) + "\n")
        _log_file.flush()
    except Exception:
        pass  # never break the agent
