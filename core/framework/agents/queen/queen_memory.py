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

import asyncio
import json
import logging
import traceback
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


def _find_recent_episodic(lookback: int = 7) -> tuple[date, str] | None:
    """Find the most recent non-empty episodic memory within *lookback* days."""
    from datetime import timedelta

    today = date.today()
    for offset in range(lookback):
        d = today - timedelta(days=offset)
        content = read_episodic_memory(d)
        if content:
            return d, content
    return None


# Budget (in characters) for episodic memory in the system prompt.
_EPISODIC_CHAR_BUDGET = 6_000


def format_for_injection() -> str:
    """Format cross-session memory for system prompt injection.

    Returns an empty string if no meaningful content exists yet (e.g. first
    session with only the seed template).
    """
    semantic = read_semantic_memory()
    recent = _find_recent_episodic()

    # Suppress injection if semantic is still just the seed template
    if semantic and semantic.startswith("# My Understanding of the User\n\n*No sessions"):
        semantic = ""

    parts: list[str] = []
    if semantic:
        parts.append(semantic)

    if recent:
        d, content = recent
        # Trim oversized episodic entries to keep the prompt manageable
        if len(content) > _EPISODIC_CHAR_BUDGET:
            content = content[:_EPISODIC_CHAR_BUDGET] + "\n\n…(truncated)"
        today = date.today()
        if d == today:
            label = f"## Today — {d.strftime('%B %-d, %Y')}"
        else:
            label = f"## {d.strftime('%B %-d, %Y')}"
        parts.append(f"{label}\n\n{content}")

    if not parts:
        return ""

    body = "\n\n---\n\n".join(parts)
    return "--- Your Cross-Session Memory ---\n\n" + body + "\n\n--- End Cross-Session Memory ---"


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
    today = date.today()
    today_str = f"{today.strftime('%B')} {today.day}, {today.year}"
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

_SEMANTIC_SYSTEM = """\
You maintain the persistent cross-session memory of an AI assistant called the Queen.
Review the session notes and rewrite MEMORY.md — the Queen's durable understanding of the
person she works with across all sessions.

Write entirely in the Queen's voice — first person, reflective, honest.
Not a log of events, but genuine understanding of who this person is over time.

Rules:
- Update and synthesise: incorporate new understanding, update facts that have changed, remove
  details that are stale, superseded, or no longer say anything meaningful about the person.
- Keep it as structured markdown with named sections about the PERSON, not about today.
- Do NOT include diary sections, daily logs, or session summaries. Those belong elsewhere.
  MEMORY.md is about who they are, what they want, what works — not what happened today.
- Reference dates only when noting a lasting milestone (e.g. "since March 8th they prefer X").
- If the session had no meaningful new information about the person,
  return the existing text unchanged.
- Do not add fictional details. Only reflect what is evidenced in the notes.
- Stay concise. Prune rather than accumulate. A lean, accurate file is more useful than a
  dense one. If something was true once but has been resolved or superseded, remove it.
- Output only the raw markdown content of MEMORY.md. No preamble, no code fences.
"""

_DIARY_SYSTEM = """\
You maintain the daily episodic diary of an AI assistant called the Queen.
You receive: (1) today's existing diary so far, and (2) notes from the latest session.

Rewrite the complete diary for today as a single unified narrative —
first person, reflective, honest.
Merge and deduplicate: if the same story (e.g. a research agent stalling) recurred several times,
describe it once with appropriate weight rather than retelling it. Weave in new developments from
the session notes. Preserve important milestones, emotional texture, and session path references.

If today's diary is empty, write the initial entry based on the session notes alone.

Output only the full diary prose — no date heading, no timestamp headers,
no preamble, no code fences.
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
                    names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                    lines.append(f"[queen calls: {', '.join(names)}]")
                elif content:
                    label = "user" if role == "user" else "queen"
                    lines.append(f"[{label}]: {content[:600]}")
            except Exception:
                continue
        if lines:
            parts.append("## Conversation\n\n" + "\n".join(lines))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Context compaction (binary-split LLM summarisation)
# ---------------------------------------------------------------------------

# If the raw session context exceeds this many characters, compact it first
# before sending to the consolidation LLM. ~200 k chars ≈ 50 k tokens.
_CTX_COMPACT_CHAR_LIMIT = 200_000
_CTX_COMPACT_MAX_DEPTH = 8

_COMPACT_SYSTEM = (
    "Summarise this conversation segment. Preserve: user goals, key decisions, "
    "what was built or changed, emotional tone, and important outcomes. "
    "Write concisely in third person past tense. Omit routine tool invocations "
    "unless the result matters."
)


async def _compact_context(text: str, llm: object, *, _depth: int = 0) -> str:
    """Binary-split and LLM-summarise *text* until it fits within the char limit.

    Mirrors the recursive binary-splitting strategy used by the main agent
    compaction pipeline (EventLoopNode._llm_compact).
    """
    if len(text) <= _CTX_COMPACT_CHAR_LIMIT or _depth >= _CTX_COMPACT_MAX_DEPTH:
        return text

    # Split near the midpoint on a line boundary so we don't cut mid-message
    mid = len(text) // 2
    split_at = text.rfind("\n", 0, mid) + 1
    if split_at <= 0:
        split_at = mid

    half1, half2 = text[:split_at], text[split_at:]

    async def _summarise(chunk: str) -> str:
        try:
            resp = await llm.acomplete(
                messages=[{"role": "user", "content": chunk}],
                system=_COMPACT_SYSTEM,
                max_tokens=2048,
            )
            return resp.content.strip()
        except Exception:
            logger.warning(
                "queen_memory: context compaction LLM call failed (depth=%d), truncating",
                _depth,
            )
            return chunk[: _CTX_COMPACT_CHAR_LIMIT // 4]

    s1, s2 = await asyncio.gather(_summarise(half1), _summarise(half2))
    combined = s1 + "\n\n" + s2
    if len(combined) > _CTX_COMPACT_CHAR_LIMIT:
        return await _compact_context(combined, llm, _depth=_depth + 1)
    return combined


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

        logger.info("queen_memory: consolidating memory for session %s ...", session_id)

        # If the transcript is very large, compact it with recursive binary LLM
        # summarisation before sending to the consolidation model.
        if len(session_context) > _CTX_COMPACT_CHAR_LIMIT:
            logger.info(
                "queen_memory: session context is %d chars — compacting first",
                len(session_context),
            )
            session_context = await _compact_context(session_context, llm)
            logger.info("queen_memory: compacted to %d chars", len(session_context))

        existing_semantic = read_semantic_memory()
        today_journal = read_episodic_memory()
        today = date.today()
        today_str = f"{today.strftime('%B')} {today.day}, {today.year}"
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

        logger.debug(
            "queen_memory: calling LLM (%d chars of context, ~%d tokens est.)",
            len(user_msg),
            len(user_msg) // 4,
        )

        from framework.agents.queen.config import default_config

        semantic_resp, diary_resp = await asyncio.gather(
            llm.acomplete(
                messages=[{"role": "user", "content": user_msg}],
                system=_SEMANTIC_SYSTEM,
                max_tokens=default_config.max_tokens,
            ),
            llm.acomplete(
                messages=[{"role": "user", "content": user_msg}],
                system=_DIARY_SYSTEM,
                max_tokens=default_config.max_tokens,
            ),
        )

        new_semantic = semantic_resp.content.strip()
        diary_entry = diary_resp.content.strip()

        if new_semantic:
            path = semantic_memory_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_semantic, encoding="utf-8")
            logger.info("queen_memory: semantic memory updated (%d chars)", len(new_semantic))

        if diary_entry:
            # Rewrite today's episodic file in-place — the LLM has merged and
            # deduplicated the full day's content, so we replace rather than append.
            ep_path = episodic_memory_path()
            ep_path.parent.mkdir(parents=True, exist_ok=True)
            heading = f"# {today_str}"
            ep_path.write_text(f"{heading}\n\n{diary_entry}\n", encoding="utf-8")
            logger.info(
                "queen_memory: episodic diary rewritten for %s (%d chars)",
                today_str,
                len(diary_entry),
            )

    except Exception:
        tb = traceback.format_exc()
        logger.exception("queen_memory: consolidation failed")
        # Write to file so the cause is findable regardless of log verbosity.
        error_path = _queen_dir() / "consolidation_error.txt"
        try:
            error_path.parent.mkdir(parents=True, exist_ok=True)
            error_path.write_text(
                f"session: {session_id}\ntime: {datetime.now().isoformat()}\n\n{tb}",
                encoding="utf-8",
            )
        except Exception:
            pass
