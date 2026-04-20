"""One-shot LLM gate that decides if a queen DM is ready to fork a colony.

The queen's ``start_incubating_colony`` tool calls :func:`evaluate` with
the queen's recent conversation, a proposed ``colony_name``, and a
one-paragraph ``intended_purpose``.  The evaluator returns a structured
verdict:

    {
        "ready": bool,
        "reasons": [str],
        "missing_prerequisites": [str],
    }

On ``ready=False`` the queen receives the verdict as her tool result and
self-corrects (asks the user, refines scope, drops the idea).  On
``ready=True`` the tool flips the queen's phase to ``incubating``.

Failure mode is **fail-closed**: any LLM error or unparseable response
returns ``ready=False`` with reason ``"evaluation_failed"`` so the queen
cannot accidentally proceed past a broken gate.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from framework.agent_loop.conversation import Message

logger = logging.getLogger(__name__)


_INCUBATING_EVALUATOR_SYSTEM_PROMPT = """\
You gate whether a queen agent should commit to forking a persistent
"colony" (a headless worker spec written to disk).  Forking is
expensive: it ends the user's chat with this queen and the worker runs
unattended afterward, so the spec must be settled before you approve.

Read the conversation excerpt and the queen's proposed colony_name +
intended_purpose, then decide.

APPROVE (ready=true) only when ALL of the following hold:
  1. The user has explicitly asked for work that needs to outlive this
     chat — recurring (cron / interval), monitoring + alert, scheduled
     batch, or "fire-and-forget background job".  A one-shot question
     that the queen can answer in chat does NOT qualify.
  2. The scope of the work is concrete enough to write down — what
     inputs, what outputs, what success looks like.  Vague ("help me
     with my workflow") does NOT qualify.
  3. The technical approach is at least sketched — what data sources,
     APIs, or tools the worker will use.  The queen does not have to
     have written the SKILL.md yet, but she must have the operational
     ingredients available.
  4. There are no open clarifying questions on the table that the user
     hasn't answered.  If the queen recently asked the user something
     and is still waiting, do NOT approve.

REJECT (ready=false) on any of:
  - Conversation is too short / too generic to support a settled spec.
  - User is still describing what they want.
  - User has expressed doubts, change-of-direction, or "let me think".
  - Work is one-shot and could be done in chat instead.
  - Open question awaiting user reply.

Reply with a JSON object exactly matching this shape:

  {
    "ready": true | false,
    "reasons": ["short phrase", ...],         // at least one entry
    "missing_prerequisites": ["short phrase", ...]  // empty when ready
  }

``reasons`` explains the verdict in 1-3 short phrases.
``missing_prerequisites`` lists what's missing in queen-actionable
form ("user hasn't confirmed schedule", "no API auth flow discussed").
Empty list when ``ready=true``.

Output JSON only.  Do not wrap in markdown.  Do not add prose.
"""


# Bound the formatted excerpt so the eval call stays cheap and fits well
# under the LLM's context window even for long DM sessions.
_MAX_MESSAGES = 30
_MAX_TOOL_CONTENT_CHARS = 400
_MAX_USER_CONTENT_CHARS = 2_000
_MAX_ASSISTANT_CONTENT_CHARS = 2_000


def format_conversation_excerpt(messages: list[Message]) -> str:
    """Format the tail of a queen conversation for the evaluator prompt.

    Keeps the most recent ``_MAX_MESSAGES`` messages.  Tool results are
    truncated hard since they're rarely load-bearing for the readiness
    decision; user/assistant text is truncated more generously to
    preserve the actual conversation signal.
    """
    if not messages:
        return "(no messages)"

    tail = messages[-_MAX_MESSAGES:]
    parts: list[str] = []
    for msg in tail:
        role = msg.role.upper()
        content = (msg.content or "").strip()
        if msg.role == "tool":
            if len(content) > _MAX_TOOL_CONTENT_CHARS:
                content = content[:_MAX_TOOL_CONTENT_CHARS] + "..."
        elif msg.role == "assistant":
            # Surface tool-call intent for empty assistant turns so the
            # evaluator sees what the queen has been doing.
            if not content and msg.tool_calls:
                names = [
                    tc.get("function", {}).get("name", "?")
                    for tc in msg.tool_calls
                ]
                content = f"(called: {', '.join(names)})"
            if len(content) > _MAX_ASSISTANT_CONTENT_CHARS:
                content = content[:_MAX_ASSISTANT_CONTENT_CHARS] + "..."
        else:  # user
            if len(content) > _MAX_USER_CONTENT_CHARS:
                content = content[:_MAX_USER_CONTENT_CHARS] + "..."
        if content:
            parts.append(f"[{role}]: {content}")

    return "\n\n".join(parts) if parts else "(no messages)"


def _build_user_message(
    conversation_excerpt: str,
    colony_name: str,
    intended_purpose: str,
) -> str:
    return (
        f"## Proposed colony name\n{colony_name}\n\n"
        f"## Queen's intended_purpose\n{intended_purpose.strip()}\n\n"
        f"## Recent conversation (oldest → newest)\n{conversation_excerpt}\n\n"
        "Decide: should this queen be approved to enter INCUBATING phase?"
    )


def _parse_verdict(raw: str) -> dict[str, Any] | None:
    """Parse the evaluator's JSON.  Returns None if parsing fails."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Some models wrap JSON in markdown fences or add preamble.
        # Pull the first { ... } block out as a best-effort fallback —
        # mirrors the same recovery pattern used in recall_selector.py.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def _normalize_verdict(parsed: dict[str, Any]) -> dict[str, Any]:
    """Coerce a parsed verdict into the shape the tool returns to the queen."""
    ready = bool(parsed.get("ready"))
    reasons = parsed.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    reasons = [str(r).strip() for r in reasons if str(r).strip()]
    missing = parsed.get("missing_prerequisites") or []
    if isinstance(missing, str):
        missing = [missing]
    missing = [str(m).strip() for m in missing if str(m).strip()]

    if ready:
        # When approved we don't surface missing prerequisites — the
        # incubating role prompt opens that floor itself.
        missing = []
    elif not reasons:
        # Always give the queen at least one reason to reflect on.
        reasons = ["evaluator returned no reasons"]

    return {
        "ready": ready,
        "reasons": reasons,
        "missing_prerequisites": missing,
    }


async def evaluate(
    llm: Any,
    messages: list[Message],
    colony_name: str,
    intended_purpose: str,
) -> dict[str, Any]:
    """Run the incubating evaluator against the queen's conversation.

    Args:
        llm: An LLM provider exposing ``acomplete(messages, system, ...)``.
            Pass the queen's own ``ctx.llm`` so the eval uses the same
            model the user is talking to.
        messages: The queen's conversation messages, oldest first.  The
            evaluator slices its own tail; pass the full list.
        colony_name: Validated colony slug.
        intended_purpose: Queen's one-paragraph brief.

    Returns:
        ``{"ready": bool, "reasons": [str], "missing_prerequisites": [str]}``.
        Fail-closed on any error.
    """
    excerpt = format_conversation_excerpt(messages)
    user_msg = _build_user_message(excerpt, colony_name, intended_purpose)

    try:
        response = await llm.acomplete(
            messages=[{"role": "user", "content": user_msg}],
            system=_INCUBATING_EVALUATOR_SYSTEM_PROMPT,
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
    except Exception as exc:  # noqa: BLE001 - fail-closed on any LLM failure
        logger.warning("incubating_evaluator: LLM call failed (%s)", exc)
        return {
            "ready": False,
            "reasons": ["evaluation_failed"],
            "missing_prerequisites": [
                "evaluator LLM call failed; retry once the queen can reach the model again"
            ],
        }

    raw = (getattr(response, "content", "") or "").strip()
    parsed = _parse_verdict(raw)
    if parsed is None:
        logger.warning(
            "incubating_evaluator: could not parse JSON verdict (raw=%.200s)",
            raw,
        )
        return {
            "ready": False,
            "reasons": ["evaluation_failed"],
            "missing_prerequisites": [
                "evaluator returned malformed JSON; retry"
            ],
        }

    return _normalize_verdict(parsed)
