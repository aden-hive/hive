"""``list_queens`` and ``message_queen``: queens writing to each other (:mod:`framework.server.queen_mail`).

Registered only when ``queen_mail`` is on in configuration.json and the queen takes part in it.
"""

from __future__ import annotations

import json
from typing import Any


def register_queen_mail_tools(registry: Any, session: Any = None, session_manager: Any = None) -> int:
    """Register the two tools on a queen's ``registry``; returns how many were registered."""
    from framework.config import get_queen_mail_config
    from framework.llm.provider import Tool
    from framework.server.queen_mail import QueenMailError

    config = get_queen_mail_config()
    # A queen picked for the session later (no queen_name yet) is checked when she writes.
    queen_id = getattr(session, "queen_name", None)
    if session is None or not config.enabled or (queen_id and not config.includes(queen_id)):
        return 0

    def mail() -> Any:
        mail = getattr(session_manager, "queen_mail", None)
        if mail is None:
            raise QueenMailError("Queen mail isn't running in this server")
        return mail

    async def list_queens() -> str:
        try:
            queens = mail().correspondents(getattr(session, "queen_name", None))
        except QueenMailError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps({"queens": queens}, ensure_ascii=False)

    async def message_queen(queen_id: str, message: str) -> str:
        try:
            sent = await mail().send(session, queen_id, message)
        except QueenMailError as e:
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        return json.dumps(sent, ensure_ascii=False)

    registry.register(
        "list_queens",
        Tool(
            name="list_queens",
            description="The other queens you can write to with message_queen: each one's id, name and title.",
            parameters={"type": "object", "properties": {}},
        ),
        lambda inputs: list_queens(),
    )
    registry.register(
        "message_queen",
        Tool(
            name="message_queen",
            description=(
                "Write to another queen. It returns at once; her answer arrives later as a message from her, "
                '"[Name(queen_id)]: ...", and each time you write she goes on with the same conversation with you. '
                "When another queen writes to you, just answer: your reply goes back to her without this tool. "
                "Returns {sent, to, depth}, or {error} (no such queen, today's limit reached, or the chain of letters "
                "that led here is too long)." + _roster(session_manager, queen_id)
            ),
            parameters={
                "type": "object",
                "properties": {
                    "queen_id": {"type": "string", "description": "Her id, from list_queens."},
                    "message": {
                        "type": "string",
                        "description": "What to tell her. She can't see your conversation, so say what she needs to know.",
                    },
                },
                "required": ["queen_id", "message"],
            },
        ),
        lambda inputs: message_queen(str(inputs.get("queen_id") or ""), str(inputs.get("message") or "")),
    )
    return 2


def _roster(session_manager: Any, queen_id: str | None) -> str:
    """Who she can write to, as the session starts (list_queens has it as it is now); "" when unknown."""
    mail = getattr(session_manager, "queen_mail", None)
    if mail is None or not queen_id:
        return ""
    queens = mail.correspondents(queen_id)
    if not queens:
        return ""
    return (
        " Queens you can write to: "
        + "; ".join(f"{q['name']} ({q['id']}, {q['title']})" if q["title"] else f"{q['name']} ({q['id']})" for q in queens)
        + "."
    )
