"""Queen global cross-session memory.

Three-tier memory architecture:
  ~/.hive/queen/MEMORY.md                            — semantic (who, what, why)
  ~/.hive/queen/memories/MEMORY-YYYY-MM-DD.md        — episodic (daily journals)
  ~/.hive/queen/session/{id}/data/adapt.md           — working (session-scoped)

Semantic and episodic files are injected at queen session start.

Semantic memory (MEMORY.md) is updated automatically at session end via
consolidate_queen_memory() — the queen never rewrites this herself.

Episodic memory (MEMORY-date.md) can be written by the queen during a session
via the write_to_diary tool, and is also appended to at session end by
consolidate_queen_memory().
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _queen_dir() -> Path:
    return Path.home() / ".hive" / "queen"


def semantic_memory_path() -> Path:
    return _queen_dir() / "MEMORY.md"


def episodic_memory_path(d: date | None = None) -> Path:
    d = d or date.today()
    return _queen_dir() / "memories" / f"MEMORY-{d.strftime('%Y-%m-%d')}.md"


def read_semantic_memory() -> str:
    path = semantic_memory_path()
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def read_episodic_memory(d: date | None = None) -> str:
    path = episodic_memory_path(d)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def format_for_injection() -> str:
    """Format cross-session memory for system prompt injection.

    Returns an empty string if no meaningful content exists yet (e.g. first
    session with only the seed template).
    """
    semantic = read_semantic_memory()
    episodic = read_episodic_memory()

    # Suppress injection if semantic is still just the seed template
    if semantic and semantic.startswith("# My Understanding of the User\n\n*No sessions"):
        semantic = ""

    parts: list[str] = []
    if semantic:
        parts.append(semantic)
    if episodic:
        today_str = date.today().strftime("%B %-d, %Y")
        parts.append(f"## Today — {today_str}\n\n{episodic}")

    if not parts:
        return ""

    body = "\n\n---\n\n".join(parts)
    return (
        "--- Your Cross-Session Memory ---\n\n"
        + body
        + "\n\n--- End Cross-Session Memory ---"
    )


_SEED_TEMPLATE = """\
# My Understanding of the User

*No sessions recorded yet.*

## Who They Are

## What They're Trying to Achieve

## What's Working

## What I've Learned
"""


def append_episodic_entry(content: str) -> None:
    """Append a timestamped prose entry to today's episodic memory file.

    Creates the file (with a date heading) if it doesn't exist yet.
    Used both by the queen's diary tool and by the consolidation hook.
    """
    ep_path = episodic_memory_path()
    ep_path.parent.mkdir(parents=True, exist_ok=True)
    today_str = date.today().strftime("%B %-d, %Y")
    timestamp = datetime.now().strftime("%H:%M")
    if not ep_path.exists():
        header = f"# {today_str}\n\n"
        block = f"{header}### {timestamp}\n\n{content.strip()}\n"
    else:
        block = f"\n\n### {timestamp}\n\n{content.strip()}\n"
    with ep_path.open("a", encoding="utf-8") as f:
        f.write(block)


def seed_if_missing() -> None:
    """Create MEMORY.md with a blank template if it doesn't exist yet."""
    path = semantic_memory_path()
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_SEED_TEMPLATE, encoding="utf-8")


# ---------------------------------------------------------------------------
# Consolidation prompt
# ---------------------------------------------------------------------------

_CONSOLIDATION_SYSTEM = """\
You maintain the persistent cross-session memory of an AI assistant called \
the Queen. After each session you review what happened and update two files.

You write entirely in the Queen's voice — first person, reflective, honest. \
Not a ledger of events, but genuine understanding of the person she works with.

Respond with a JSON object containing exactly two keys:
  "semantic_memory"  — the full new content of MEMORY.md
  "diary_entry"      — a prose entry for today's episodic memory

Rules:
- semantic_memory: preserve all existing facts; update or expand based on \
this session. Keep it as MEMORY.md — structured markdown with named sections. \
Reference dates when significant milestones occurred so they connect to \
episodic files (e.g. "since March 8th", "as of early February").
- diary_entry: one or two paragraphs about what happened in this session \
as the Queen would write it. Include the full session adapt.md path at the \
end as a plain-text reference line, on its own line.
- If the session had no meaningful content, return semantic_memory unchanged \
and write a brief diary_entry noting it was a quiet session.
- Do not add fictional details. Only reflect what is evidenced in the notes.
"""


def read_session_context(session_dir: Path, max_messages: int = 80) -> str:
    """Extract a readable transcript from conversation parts + adapt.md.

    Reads the last ``max_messages`` conversation parts and the session's
    adapt.md (working memory). Tool results are omitted — only user and
    assistant turns (with tool-call names noted) are included.
    """
    parts: list[str] = []

    # Working notes
    adapt_path = session_dir / "data" / "adapt.md"
    if adapt_path.exists():
        text = adapt_path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"## Session Working Notes (adapt.md)\n\n{text}")

    # Conversation transcript
    parts_dir = session_dir / "conversations" / "parts"
    if parts_dir.exists():
        part_files = sorted(parts_dir.glob("*.json"))[-max_messages:]
        lines: list[str] = []
        for pf in part_files:
            try:
                data = json.loads(pf.read_text(encoding="utf-8"))
                role = data.get("role", "")
                content = str(data.get("content", "")).strip()
                tool_calls = data.get("tool_calls") or []
                if role == "tool":
                    continue  # skip verbose tool results
                if role == "assistant" and tool_calls and not content:
                    names = [
                        tc.get("function", {}).get("name", "?")
                        for tc in tool_calls
                    ]
                    lines.append(f"[queen calls: {', '.join(names)}]")
                elif content:
                    label = "user" if role == "user" else "queen"
                    lines.append(f"[{label}]: {content[:600]}")
            except Exception:
                continue
        if lines:
            parts.append("## Conversation\n\n" + "\n".join(lines))

    return "\n\n".join(parts)


async def consolidate_queen_memory(
    session_id: str,
    session_dir: Path,
    llm: object,
) -> None:
    """Update MEMORY.md and append a diary entry based on the current session.

    Reads conversation parts and adapt.md from session_dir. Called
    periodically in the background and once at session end. Failures are
    logged and silently swallowed so they never block teardown.

    Args:
        session_id: The session ID (used for the adapt.md path reference).
        session_dir: Path to the session directory (~/.hive/queen/session/{id}).
        llm: LLMProvider instance (must support acomplete()).
    """
    try:
        session_context = read_session_context(session_dir)
        if not session_context:
            logger.debug("queen_memory: no session context, skipping consolidation")
            return

        existing_semantic = read_semantic_memory()
        today_journal = read_episodic_memory()
        today_str = date.today().strftime("%B %-d, %Y")
        adapt_path = session_dir / "data" / "adapt.md"

        user_msg = (
            f"## Existing Semantic Memory (MEMORY.md)\n\n"
            f"{existing_semantic or '(none yet)'}\n\n"
            f"## Today's Diary So Far ({today_str})\n\n"
            f"{today_journal or '(none yet)'}\n\n"
            f"{session_context}\n\n"
            f"## Session Reference\n\n"
            f"Session ID: {session_id}\n"
            f"Session path: {adapt_path}\n"
        )

        response = await llm.acomplete(
            messages=[{"role": "user", "content": user_msg}],
            system=_CONSOLIDATION_SYSTEM,
            max_tokens=2048,
            json_mode=True,
        )

        data = json.loads(response.content)
        new_semantic: str = data.get("semantic_memory", "").strip()
        diary_entry: str = data.get("diary_entry", "").strip()

        if new_semantic:
            path = semantic_memory_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_semantic, encoding="utf-8")
            logger.info("queen_memory: semantic memory updated (%d chars)", len(new_semantic))

        if diary_entry:
            append_episodic_entry(diary_entry)
            logger.info("queen_memory: diary entry written for %s", today_str)

    except Exception:
        logger.warning("queen_memory: consolidation failed", exc_info=True)
