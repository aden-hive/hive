"""Stall check: catch a queen turn that announced work and ended without doing it.

Some models write "on it, drawing now" and end the turn without the tool call
that would do it. With the Developer option ``stall_check`` on and a judge in
the ``judge`` slot, every queen turn that ends waiting for the user is put to
the judge: the user's message, the queen's last reasoning and reply, and the
tools she called. When the judge says she announced an action she never took
(probability at or above the slot's ``threshold``, 0.5 by default), she gets
one reminder to carry it out. At most one reminder per user message, so a
mistaken judgment can't loop.

The judge is the one in the ``judge`` slot (see ``framework.server.judge``).
Both the option and the slot are read when a turn ends, so turning the check
on or off, or changing the judge, applies to running sessions at once.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from framework.server import judge

logger = logging.getLogger(__name__)

_QUESTION = (
    "In its final reply the assistant said, or its reasoning shows, that it was about to take an action "
    "(run a command, call a tool, draw or send an image, look something up) in this turn, but the turn "
    "ended without that action happening: no tool call in this turn did it."
)
REMINDER = (
    "<system-reminder>\n"
    "Your last reply announced an action, but you ended the turn without calling any tool to do it, so "
    "nothing happened. If you meant to do it, call the tools now. If not, carry on. "
    "Don't mention this reminder.\n"
    "</system-reminder>"
)


def judge_slot() -> dict[str, Any] | None:
    """The configured ``judge`` slot, when the stall check is on and the slot is usable."""
    from framework.config import get_stall_check_enabled

    return judge.slot() if get_stall_check_enabled() else None


def subscribe_stall_check(
    event_bus: Any,
    queen_node: Callable[[], Any],
    *,
    judges: dict[str, judge.Protocol] | None = None,
) -> list[str]:
    """Watch the queen's turns on ``event_bus``; ``queen_node()`` returns the node to remind."""
    from framework.agent_loop.visible_error import is_visible_error
    from framework.host.event_bus import EventType

    turn: dict[str, Any] = {"user": "", "reasoning": "", "reply": "", "tools": [], "judged": False}
    running: set[asyncio.Task[None]] = set()

    async def check(user: str, reasoning: str, reply: str, tools: list[str]) -> None:
        slot = judge_slot()
        if slot is None:
            return
        state = {
            "user_message": user[-2000:],
            "assistant_reasoning_tail": reasoning[-1500:],
            "assistant_reply": reply[-1500:],
            "tools_called_this_turn": tools,
        }
        p = await judge.ask(_QUESTION, state, protocols=judges)
        if p is None:
            return
        threshold = float(slot.get("threshold", 0.5))
        if p < threshold:
            logger.debug("stall check: p=%.2f < %.2f, turn is fine", p, threshold)
            return
        node = queen_node()
        if node is None or not hasattr(node, "inject_event"):
            return
        logger.info("stall check: p=%.2f >= %.2f, reminding the queen to carry out what she announced", p, threshold)
        await node.inject_event(REMINDER, is_client_input=False)

    async def on_event(event: Any) -> None:
        if getattr(event, "stream_id", None) != "queen":
            return
        data = event.data or {}
        if event.type == EventType.CLIENT_INPUT_RECEIVED:
            turn.update(user=str(data.get("content") or ""), reasoning="", reply="", tools=[], judged=False)
        elif event.type == EventType.CLIENT_REASONING:
            turn["reasoning"] = str(data.get("reasoning") or turn["reasoning"])
        elif event.type == EventType.CLIENT_OUTPUT_DELTA:
            turn["reply"] = str(data.get("snapshot") or turn["reply"])
        elif event.type == EventType.TOOL_CALL_STARTED:
            # Another model call follows: what matters is the reasoning and reply of the last one.
            turn["tools"].append(str(data.get("tool_name") or ""))
            turn.update(reasoning="", reply="")
        elif event.type == EventType.CLIENT_INPUT_REQUESTED and data.get("park_reason") == "turn_done":
            # A failed model call (even one a gateway returned as a reply) announced nothing.
            if turn["judged"] or not turn["user"] or not turn["reply"].strip() or is_visible_error(turn["reply"]):
                return
            turn["judged"] = True  # one judgment, and at most one reminder, per user message
            task = asyncio.create_task(check(turn["user"], turn["reasoning"], turn["reply"], list(turn["tools"])))
            running.add(task)
            task.add_done_callback(running.discard)

    return [
        event_bus.subscribe(
            event_types=[
                EventType.CLIENT_INPUT_RECEIVED,
                EventType.CLIENT_REASONING,
                EventType.CLIENT_OUTPUT_DELTA,
                EventType.TOOL_CALL_STARTED,
                EventType.CLIENT_INPUT_REQUESTED,
            ],
            handler=on_event,
        )
    ]
