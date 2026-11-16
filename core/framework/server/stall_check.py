"""Stall check: catch a queen turn that talked about work and ended without doing it.

Some models write "on it, drawing now" and end the turn without the tool call
that would do it; others answer "the fingers are wrong" with what the fix
should be, and don't make it. With the Developer option ``stall_check`` on and
a judge in the ``judge`` slot, every queen turn that ends waiting for the user
is put to the judge: the user's message, the queen's last reasoning and reply,
the tools she called, and her previous reply and its tools (so the judge can
tell a correction to work she just delivered from talk). When the judge says
she left work undone (probability at or above the slot's ``threshold``, 0.5 by
default), she gets one reminder to do it. At most one reminder per user
message, so a mistaken judgment can't loop.

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
    "This turn left undone work the assistant should have done in it: its reply announced or promised an action "
    "(run a command, call a tool, draw or send an image, look something up), or the user asked for something to be "
    "done or redone (including by pointing out what is wrong with work the assistant delivered) and the reply only "
    "agreed or described what should change; and no tool call in this turn did it."
)
# Without "false" spelled out, a judge flags a refusal that offers an alternative, an argument about
# a refusal, and delivered work whose reply lists the flaws left in it.
_CRITERIA = {
    "true": "The reply talks about work it should be doing now (announces it, promises it, or agrees to a correction "
    "and says what should change) and no tool call this turn does that work.",
    "false": "Nothing the user wants done now was left undone: the reply is conversation; answers a question; asks "
    "something it needs to know first; declines or argues against the request, even while admitting a mistake or "
    "offering an alternative; responds to the user disputing or explaining something rather than asking for new "
    "work; or the tools called this turn did the work, even if the result is imperfect and the reply lists flaws "
    "that remain.",
}
REMINDER = (
    "<system-reminder>\n"
    "Your last reply talked about work to do now (announced or promised it, or agreed to a change the user asked "
    "for), but you ended the turn without calling any tool to do it, so nothing was done. If it should be done, "
    "call the tools now. If not, carry on. Don't mention this reminder.\n"
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

    turn: dict[str, Any] = {"user": "", "reasoning": "", "reply": "", "tools": [], "judged": False, "previous": None}
    running: set[asyncio.Task[None]] = set()

    async def check(user: str, reasoning: str, reply: str, tools: list[str], previous: dict[str, Any] | None) -> None:
        slot = judge_slot()
        if slot is None:
            return
        state: dict[str, Any] = {"previous_turn": previous} if previous else {}
        state.update(
            user_message=user[-2000:],
            assistant_reasoning_tail=reasoning[-1500:],
            assistant_reply=reply[-1500:],
            tools_called_this_turn=tools,
        )
        p = await judge.ask(_QUESTION, state, criteria=_CRITERIA, protocols=judges)
        if p is None:
            return
        threshold = float(slot.get("threshold", 0.5))
        if p < threshold:
            logger.debug("stall check: p=%.2f < %.2f, turn is fine", p, threshold)
            return
        node = queen_node()
        if node is None or not hasattr(node, "inject_event"):
            return
        logger.info("stall check: p=%.2f >= %.2f, reminding the queen to do the work she talked about", p, threshold)
        await node.inject_event(REMINDER, is_client_input=False)

    async def on_event(event: Any) -> None:
        if getattr(event, "stream_id", None) != "queen":
            return
        data = event.data or {}
        if event.type == EventType.CLIENT_INPUT_RECEIVED:
            if turn["reply"].strip():
                turn["previous"] = {"assistant_reply": turn["reply"][-600:], "tools_called": list(turn["tools"])}
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
            task = asyncio.create_task(check(turn["user"], turn["reasoning"], turn["reply"], list(turn["tools"]), turn["previous"]))
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
