"""Session memory for the OpenRouter agent.

Persists a plain-text summary of each conversation to:
    ~/.hive/openrouter_agent/MEMORY.md

On session start, that file is injected into the system prompt so the
agent remembers context across runs.

Mirrors the pattern in framework/agents/queen/queen_memory.py but uses
a single flat file rather than the three-tier (semantic + episodic +
working) architecture — appropriate for a general-purpose chat agent.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_AGENT_DIR = Path.home() / ".hive" / "openrouter_agent"
_MEMORY_FILE = _AGENT_DIR / "MEMORY.md"

_SEED_TEMPLATE = """\
# OpenRouter Agent Memory

*No sessions recorded yet.*

## What the user has asked about

## Preferences and context

## Ongoing topics
"""

_CONSOLIDATION_SYSTEM = """\
You are maintaining the persistent memory of a general-purpose AI assistant.
Given the conversation transcript below, rewrite MEMORY.md — a short durable
summary of what the user cares about, their preferences, and any useful context.

Rules:
- Write in first person from the assistant's perspective.
- Be concise. 200 words maximum.
- Do not include a session log or timestamps — only durable facts and context.
- If the conversation had no meaningful new information, return the existing text unchanged.
- Output only raw markdown. No preamble, no code fences.
"""


def read_memory() -> str:
    """Read the current memory file. Returns empty string if none exists."""
    if not _MEMORY_FILE.exists():
        return ""
    content = _MEMORY_FILE.read_text(encoding="utf-8").strip()
    if content.startswith("# OpenRouter Agent Memory\n\n*No sessions recorded yet.*"):
        return ""
    return content


def format_for_injection() -> str:
    """
    Format memory for system prompt injection.
    Returns empty string on first run (no memory yet).
    """
    memory = read_memory()
    if not memory:
        return ""
    return "--- Your Memory From Previous Sessions ---\n\n" + memory + "\n\n--- End Memory ---"


def seed_if_missing() -> None:
    """Create MEMORY.md with a blank template if it does not exist yet."""
    if _MEMORY_FILE.exists():
        return
    _AGENT_DIR.mkdir(parents=True, exist_ok=True)
    _MEMORY_FILE.write_text(_SEED_TEMPLATE, encoding="utf-8")


async def consolidate_memory(
    conversation_history: list[dict],
    llm: object,
) -> None:
    """
    Rewrite MEMORY.md based on the completed conversation.

    Called at session end. Failures are logged and silently swallowed
    so they never block session teardown.

    Args:
        conversation_history: List of {"role": ..., "content": ...} dicts.
        llm: Any LLMProvider instance (must support acomplete()).
    """
    try:
        if not conversation_history:
            logger.debug("openrouter session_memory: no history, skipping consolidation")
            return

        transcript = "\n".join(
            f"{m['role'].upper()}: {m['content'][:800]}"
            for m in conversation_history
            if m.get("content")
        )

        existing = read_memory()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        user_msg = (
            f"## Existing Memory\n\n{existing or '(none yet)'}\n\n"
            f"## New Conversation ({timestamp})\n\n{transcript}"
        )

        response = await llm.acomplete(
            messages=[{"role": "user", "content": user_msg}],
            system=_CONSOLIDATION_SYSTEM,
            max_tokens=512,
        )

        new_memory = response.content.strip()
        if new_memory:
            _AGENT_DIR.mkdir(parents=True, exist_ok=True)
            _MEMORY_FILE.write_text(new_memory, encoding="utf-8")
            logger.info("openrouter session_memory: memory updated (%d chars)", len(new_memory))

    except Exception:
        logger.exception("openrouter session_memory: consolidation failed")
