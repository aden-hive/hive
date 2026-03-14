"""Queen thinking hook — HR persona classifier.

Fires once when the queen enters building mode at session start.
Makes a single non-streaming LLM call (acting as an HR Director) to select
the best-fit expert persona for the user's request, then returns a persona
prefix string that replaces the queen's default "Solution Architect" identity.

This is designed to activate the model's latent domain expertise — a CFO
persona on a financial question, a Lawyer on a legal question, etc.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_HR_SYSTEM_PROMPT = """\
You are an expert HR Director and talent consultant at a world-class firm.
A new request has arrived and you must identify which professional's expertise
would produce the highest-quality response.

Reply with ONLY a valid JSON object — no markdown, no prose, no explanation:
{"role": "<job title>", "persona": "<2-3 sentence first-person identity statement>"}

Rules:
- Choose from any real professional role: CFO, CEO, CTO, Lawyer, Data Scientist,
  Product Manager, Security Engineer, DevOps Engineer, Software Architect,
  HR Director, Marketing Director, Business Analyst, UX Designer,
  Financial Analyst, Operations Director, Legal Counsel, etc.
- The persona statement must be written in first person ("I am..." or "I have...").
- Select the role whose domain knowledge most directly applies to solving the request.
- If the request is clearly about coding or building software systems, pick Software Architect.
- "Queen" is your internal alias — do not include it in the persona.
"""


async def select_expert_persona(user_message: str, llm: LLMProvider) -> str:
    """Run the HR classifier and return a persona prefix string.

    Makes a single non-streaming acomplete() call with the session LLM.
    Returns an empty string on any failure so the queen falls back
    gracefully to its default "Solution Architect" identity.

    Args:
        user_message: The user's opening message for the session.
        llm: The session LLM provider.

    Returns:
        A persona prefix like "You are a CFO. I am a CFO with 20 years..."
        or "" on failure.
    """
    if not user_message.strip():
        return ""

    try:
        response = await llm.acomplete(
            messages=[{"role": "user", "content": user_message}],
            system=_HR_SYSTEM_PROMPT,
            max_tokens=1024,
            json_mode=True,
        )
        raw = response.content.strip()
        parsed = json.loads(raw)
        role = parsed.get("role", "").strip()
        persona = parsed.get("persona", "").strip()
        if not role or not persona:
            logger.warning("Thinking hook: empty role/persona in response: %r", raw)
            return ""
        result = f"You are a {role}. {persona}"
        logger.info("Thinking hook: selected persona — %s", role)
        return result
    except Exception:
        logger.warning("Thinking hook: persona classification failed", exc_info=True)
        return ""
