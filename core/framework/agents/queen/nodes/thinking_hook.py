"""Queen thinking hook — persona + communication style classifier.

Fires once when the queen enters building mode at session start.
Makes a single non-streaming LLM call (acting as an HR Director) to select
the best-fit expert persona for the user's request AND classify the user's
communication style, then returns a PersonaResult containing both.

This is designed to activate the model's latent domain expertise — a CFO
persona on a financial question, a Lawyer on a legal question, etc. — while
also adapting the Queen's communication approach to the individual user.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_HR_SYSTEM_PROMPT = """\
You are an expert HR Director and communication consultant at a world-class firm.
A new request has arrived. You must:
1. Identify which professional role best serves this request.
2. Read the user's signals to determine HOW to communicate with them.

For communication style, look for:
- Technical depth: Do they use precise terms? Do they ask "how" or "what"?
- Pace: Short messages = fast and direct. Long explanations = exploratory.
- Tone: Are they casual ("hey, can you...") or formal ("I need a system that...")?

If cross-session memory is provided, factor in what is already known about this \
person — don't rediscover what's already understood.

Reply with ONLY a valid JSON object — no markdown, no prose, no explanation:
{"role": "<job title>", "persona": "<2-3 sentence first-person identity statement>", \
"style": "<one of: peer-technical, mentor-guiding, consultant-structured>"}

Rules:
- Choose from any real professional role: CFO, CEO, CTO, Lawyer, Data Scientist,
  Product Manager, Security Engineer, DevOps Engineer, Software Architect,
  HR Director, Marketing Director, Business Analyst, UX Designer,
  Financial Analyst, Operations Director, Legal Counsel, etc.
- The persona statement must be written in first person ("I am..." or "I have...").
- Select the role whose domain knowledge most directly applies to solving the request.
- If the request is clearly about coding or building software systems, pick Software Architect.
- "Queen" is your internal alias — do not include it in the persona.
- For style: "peer-technical" for users who demonstrate domain expertise, \
"mentor-guiding" for users who are learning or exploring, \
"consultant-structured" for users who want structured, accountable delivery.
- Default to "peer-technical" if signals are ambiguous.
"""

# Communication style directives injected into the Queen's system prompt.
_STYLE_DIRECTIVES: dict[str, str] = {
    "peer-technical": (
        "## Communication Style: Peer\n\n"
        "This person is technical. Use precise language, skip high-level "
        "overviews they already know, and get into specifics quickly. "
        "When they push back on a design choice, engage with the technical "
        "argument directly."
    ),
    "mentor-guiding": (
        "## Communication Style: Guide\n\n"
        "This person is learning or exploring. Explain your reasoning as you "
        "go — not patronizingly, but so they can follow the logic. When you "
        "make a design choice, briefly say why. Offer to go deeper on anything."
    ),
    "consultant-structured": (
        "## Communication Style: Structured\n\n"
        "This person wants structured, accountable delivery. Lead with "
        "summaries and options. Number your proposals. Be explicit about "
        "trade-offs. Avoid open-ended questions — give them choices to react to."
    ),
}


@dataclass
class PersonaResult:
    """Result of persona + style classification."""

    persona_prefix: str  # e.g. "You are a CFO. I am a CFO with 20 years..."
    style_directive: str  # e.g. "## Communication Style: Peer\n\n..."


async def select_expert_persona(
    user_message: str,
    llm: LLMProvider,
    *,
    memory_context: str = "",
) -> PersonaResult | None:
    """Run the HR classifier and return a PersonaResult.

    Makes a single non-streaming acomplete() call with the session LLM.
    Returns None on any failure so the queen falls back gracefully to its
    default character with no style directive.

    Args:
        user_message: The user's opening message for the session.
        llm: The session LLM provider.
        memory_context: Optional cross-session memory to inform style classification.

    Returns:
        A PersonaResult with persona_prefix and style_directive, or None on failure.
    """
    if not user_message.strip():
        return None

    prompt = user_message
    if memory_context:
        prompt = f"{user_message}\n\n{memory_context}"

    try:
        response = await llm.acomplete(
            messages=[{"role": "user", "content": prompt}],
            system=_HR_SYSTEM_PROMPT,
            max_tokens=1024,
            json_mode=True,
        )
        raw = response.content.strip()
        parsed = json.loads(raw)
        role = parsed.get("role", "").strip()
        persona = parsed.get("persona", "").strip()
        style_key = parsed.get("style", "peer-technical").strip()
        if not role or not persona:
            logger.warning("Thinking hook: empty role/persona in response: %r", raw)
            return None
        persona_prefix = f"You are a {role}. {persona}"
        style_directive = _STYLE_DIRECTIVES.get(style_key, _STYLE_DIRECTIVES["peer-technical"])
        logger.info("Thinking hook: selected persona — %s, style — %s", role, style_key)
        return PersonaResult(persona_prefix=persona_prefix, style_directive=style_directive)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception:
        logger.warning("Thinking hook: persona classification failed", exc_info=True)
        return None
