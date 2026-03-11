"""Write every LLM turn to ~/.hive/llm_logs/<ts>.jsonl for replay/debugging.

Each line is a JSON object with the full LLM turn: the request payload
(system prompt + messages), assistant text, tool calls, tool results, and
token counts. The file is opened lazily on first call and flushed after every
write. Errors are silently swallowed — this must never break the agent.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

_LLM_DEBUG_DIR = Path.home() / ".hive" / "llm_logs"

_log_file: IO[str] | None = None
_log_ready = False  # lazy init guard


def _open_log() -> IO[str] | None:
    """Open the JSONL log file for this process."""
    _LLM_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _LLM_DEBUG_DIR / f"{ts}.jsonl"
    logger.info("LLM debug log → %s", path)
    return open(path, "a", encoding="utf-8")  # noqa: SIM115


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
) -> None:
    """Write one JSONL line capturing a complete LLM turn.

    Never raises.
    """
    try:
        global _log_file, _log_ready  # noqa: PLW0603
        if not _log_ready:
            _log_file = _open_log()
            _log_ready = True
        if _log_file is None:
            return
        record = {
            "timestamp": datetime.now().isoformat(),
            "node_id": node_id,
            "stream_id": stream_id,
            "execution_id": execution_id,
            "iteration": iteration,
            "system_prompt": system_prompt,
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
