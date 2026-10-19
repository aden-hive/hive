"""Automatic titles for queen sessions.

When a queen turn ends in a session that has no title yet, the worker model
(the ``worker_llm`` slot, else the queen's own model) names it from the user's
first message and the queen's latest reply. A title the user set is never
replaced. Titles live in the session's ``meta.json`` as ``title`` plus
``title_source`` (``"auto"`` or ``"user"``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 60
# How much of each message the namer sees; the opening says what a chat is about.
_EXCERPT_CHARS = 1500

_SYSTEM_PROMPT = (
    "You name chat conversations. Reply with a title of at most six words saying what the "
    "conversation is about, in the language the user writes in. No quotes, no trailing "
    "punctuation, nothing else."
)

_HIDDEN_BLOCKS = re.compile(r"<(think|system-reminder)>.*?</\1>", re.DOTALL)
_WRAPPERS = "\"'`*#“”‘’「」『』《》"
_TRAILING = ".。!！?？:：,，;；"


def clean_title(raw: str) -> str:
    """The first line of ``raw`` with quotes, markup and end punctuation
    stripped, cut to :data:`TITLE_MAX_CHARS`."""
    line = next((ln for ln in _HIDDEN_BLOCKS.sub("", raw).splitlines() if ln.strip()), "")
    title = re.sub(r"\s+", " ", line).strip(_WRAPPERS + " ").rstrip(_TRAILING).strip()
    title = re.sub(r"^title\s*[:：]\s*", "", title, flags=re.IGNORECASE)
    if len(title) > TITLE_MAX_CHARS:
        title = title[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return title


def _read_meta(session_dir: Path) -> dict[str, Any]:
    try:
        meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def read_title(session_dir: Path) -> str | None:
    title = _read_meta(session_dir).get("title")
    return title if isinstance(title, str) and title else None


def write_title(session_dir: Path, title: str, *, source: Literal["auto", "user"]) -> str | None:
    """Merge ``title`` into the session's meta.json; an empty title clears it.

    Returns the stored (cleaned) title, or None when cleared.
    """
    meta = _read_meta(session_dir)
    cleaned = clean_title(title)
    if cleaned:
        meta["title"] = cleaned
        meta["title_source"] = source
    else:
        meta.pop("title", None)
        meta.pop("title_source", None)
    tmp = session_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    tmp.replace(session_dir / "meta.json")
    return cleaned or None


async def generate_title(llm: Any, first_message: str, latest_reply: str) -> str:
    """Ask ``llm`` for a short title for a chat that opened with ``first_message``."""
    from framework.config import get_aux_max_tokens

    first = _HIDDEN_BLOCKS.sub("", first_message).strip()[:_EXCERPT_CHARS]
    reply = _HIDDEN_BLOCKS.sub("", latest_reply).strip()[:_EXCERPT_CHARS]
    resp = await llm.acomplete(
        messages=[{"role": "user", "content": f"User:\n{first}\n\nAssistant:\n{reply}"}],
        system=_SYSTEM_PROMPT,
        max_tokens=get_aux_max_tokens(),
    )
    return clean_title(resp.content or "")


def subscribe_title_trigger(event_bus: Any, session_dir: Path, llm: Any) -> list[str]:
    """Title the session after a finished queen turn, if it has no title yet.

    Publishes ``session_title_updated`` once a title is written. A failed
    attempt is retried after the next turn.
    """
    from framework.agents.queen.timeline import user_messages
    from framework.host.event_bus import AgentEvent, EventType

    latest_reply = ""
    running: asyncio.Task | None = None

    async def name_session(reply: str) -> None:
        try:
            messages = user_messages(session_dir)
            if not messages:
                return
            title = await generate_title(llm, messages[0], reply)
            # The user may have named it while the model was writing.
            if not title or read_title(session_dir):
                return
            stored = write_title(session_dir, title, source="auto")
            await event_bus.publish(
                AgentEvent(
                    type=EventType.SESSION_TITLE_UPDATED,
                    stream_id="queen",
                    data={"session_id": session_dir.name, "title": stored},
                )
            )
        except Exception:
            logger.warning("session title: naming %s failed", session_dir.name, exc_info=True)

    async def on_output(event: Any) -> None:
        nonlocal latest_reply
        if getattr(event, "stream_id", None) == "queen":
            latest_reply = (event.data or {}).get("snapshot") or latest_reply

    async def on_turn_complete(event: Any) -> None:
        nonlocal running
        if getattr(event, "stream_id", None) != "queen":
            return
        if (event.data or {}).get("stop_reason") in ("tool_use", "tool_calls"):
            return
        if not latest_reply.strip() or (running and not running.done()) or read_title(session_dir):
            return
        running = asyncio.create_task(name_session(latest_reply))

    return [
        event_bus.subscribe(event_types=[EventType.CLIENT_OUTPUT_DELTA], handler=on_output),
        event_bus.subscribe(event_types=[EventType.LLM_TURN_COMPLETE], handler=on_turn_complete),
    ]
