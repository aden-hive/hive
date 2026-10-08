"""``search_messages`` MCP tool registration.

Pulls together the three phases (sync → locate → enrich) and shapes
the result dict the LLM consumes.

Scope injection (queen / colony) is NOT a model-facing parameter — the
host framework binds the memory-tools subprocess to one session by
setting one of these env vars before launch:

    HIVE_QUEEN_ID    — DM session, queen scope (e.g. "queen_growth")
    HIVE_COLONY_NAME — colony session, colony scope

The tool reads these at call time. If neither is set, every call
returns ``{"error": "scope_unbound", ...}`` so the misconfiguration
surfaces loudly rather than silently searching the wrong owner.

Regex flags (case-insensitive, multiline, dot-all) are also NOT
parameters: callers express them inline via the standard Rust regex
flag syntax — ``(?i)foo``, ``(?m)^foo$``, ``(?s).*``. This keeps the
tool surface minimal and avoids two ways to spell the same thing.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from memory_tools import paths as P
from memory_tools.enrich import enrich
from memory_tools.index import sync_scope
from memory_tools.locate import locate

if TYPE_CHECKING:
    from fastmcp import FastMCP


# Per-parameter descriptions surface in the JSON schema FastMCP emits
# to the LLM (via pydantic's Field). Without these, parameters reach
# the model with only a name and type — no inline guidance on when /
# how to set them. Keep each description short and oriented around
# the model's decision: when would I set this? what does it do?
_PARAM_DESCRIPTIONS = {
    "pattern": (
        "Rust-style regex (RE2 subset). Plain text matches plain text — "
        "for a name, ticker, or keyword you can pass it as-is "
        "(e.g. 'AAPL', 'deadline'). Use inline flags for case-insensitive "
        "match ('(?i)stock'), line-bound ^/$ ('(?m)'), or '.' matching "
        "newlines ('(?s)'). Lookaround and backreferences are not supported."
    ),
    "session": (
        "Optional. Restrict to one session id "
        "(e.g. 'session_20260501_145636_72fa023d'). Use to drill into a "
        "specific past conversation; omit to search across all sessions."
    ),
    "role": (
        "Filter by who said it: 'user' (the user's typed messages), 'assistant' (your own prose), 'tool' (tool result bodies), or 'all' (default)."
    ),
    "match_source": (
        "'events' searches in-chat message text. 'data' searches the spilled bodies of large tool results. 'all' (default) searches both in parallel."
    ),
    "since": ("ISO date or datetime. Only sessions started on or after this point are searched. Use to scope to recent memory."),
    "until": ("ISO date or datetime. Only sessions started before this point are searched (exclusive)."),
    "max_matches": ("Cap on returned hits. Default 20. Bump up if you suspect more relevant past context exists."),
    "context": (
        "How much context to return per hit. 'turn' (default) returns "
        "the full conversational turn around the match — best for "
        "understanding what was happening. 'narrow' returns only the "
        "matched message. 'none' returns coordinates only."
    ),
    "turn_char_cap": ("Total character budget per returned turn window. Default 4000."),
    "per_message_char_cap": ("Character budget per individual message inside a turn — long messages get middle-truncated. Default 800."),
}

logger = logging.getLogger(__name__)


# Forbidden regex constructs (Rust regex / RE2 are subsets of PCRE that
# omit these). Reject up front so callers get a consistent contract no
# matter which engine ends up running.
_FORBIDDEN_RE = re.compile(r"\(\?[=!]|\(\?<[=!]|\\[1-9]")


def _validate_pattern(pattern: str) -> dict | None:
    """Return an error dict if ``pattern`` violates the contract."""
    if not pattern:
        return {"error": "regex_invalid", "message": "pattern is empty"}
    m = _FORBIDDEN_RE.search(pattern)
    if m:
        feature = m.group(0)
        kind = (
            "lookahead"
            if feature.startswith("(?=")
            else "negative_lookahead"
            if feature.startswith("(?!")
            else "lookbehind"
            if feature.startswith("(?<=")
            else "negative_lookbehind"
            if feature.startswith("(?<!")
            else "backreference"
        )
        return {
            "error": "regex_unsupported",
            "message": f"{kind} not supported (Rust-style regex / RE2 subset)",
            "feature": kind,
            "position": m.start(),
        }
    try:
        re.compile(pattern)
    except re.error as exc:
        return {
            "error": "regex_invalid",
            "message": str(exc),
            "position": getattr(exc, "pos", None),
        }
    return None


def _parse_iso(value: str | None, *, field: str) -> tuple[datetime | None, dict | None]:
    if value is None:
        return None, None
    try:
        # Accept date-only or datetime.
        if "T" in value or " " in value:
            return datetime.fromisoformat(value.replace("Z", "")), None
        return datetime.strptime(value, "%Y-%m-%d"), None
    except ValueError:
        return None, {
            "error": "filter_invalid",
            "message": f"{field}={value!r} is not a valid ISO date or datetime",
        }


def _resolve_injected_scope() -> tuple[P.Scope | None, str | None, dict | None]:
    """Read the host-injected scope binding.

    Exactly one of ``HIVE_QUEEN_ID`` / ``HIVE_COLONY_NAME`` must be set.
    Empty strings are treated as unset.
    """
    queen = os.environ.get("HIVE_QUEEN_ID") or None
    colony = os.environ.get("HIVE_COLONY_NAME") or None

    if queen and colony:
        return (
            None,
            None,
            {
                "error": "scope_unbound",
                "message": ("both HIVE_QUEEN_ID and HIVE_COLONY_NAME are set; the framework must inject exactly one"),
            },
        )
    if not queen and not colony:
        return (
            None,
            None,
            {
                "error": "scope_unbound",
                "message": ("no scope bound — framework must set HIVE_QUEEN_ID or HIVE_COLONY_NAME in the memory-tools subprocess env"),
            },
        )
    if queen:
        scope: P.Scope = "queens"
        owner = queen
    else:
        scope = "colonies"
        owner = colony  # type: ignore[assignment]
    if not P.owner_dir(scope, owner).exists():
        return (
            None,
            None,
            {
                "error": "scope_not_found",
                "message": f"{scope[:-1]} {owner!r} not found on disk",
                "available": P.list_owners(scope),
            },
        )
    return scope, owner, None


def register_search_messages(mcp: FastMCP) -> None:
    @mcp.tool()
    def search_messages(
        pattern: Annotated[str, Field(description=_PARAM_DESCRIPTIONS["pattern"])],
        session: Annotated[str | None, Field(description=_PARAM_DESCRIPTIONS["session"])] = None,
        role: Annotated[
            Literal["user", "assistant", "tool", "all"],
            Field(description=_PARAM_DESCRIPTIONS["role"]),
        ] = "all",
        match_source: Annotated[
            Literal["events", "data", "all"],
            Field(description=_PARAM_DESCRIPTIONS["match_source"]),
        ] = "all",
        since: Annotated[str | None, Field(description=_PARAM_DESCRIPTIONS["since"])] = None,
        until: Annotated[str | None, Field(description=_PARAM_DESCRIPTIONS["until"])] = None,
        max_matches: Annotated[int, Field(description=_PARAM_DESCRIPTIONS["max_matches"])] = 20,
        context: Annotated[
            Literal["none", "narrow", "turn"],
            Field(description=_PARAM_DESCRIPTIONS["context"]),
        ] = "turn",
        turn_char_cap: Annotated[int, Field(description=_PARAM_DESCRIPTIONS["turn_char_cap"])] = 4000,
        per_message_char_cap: Annotated[int, Field(description=_PARAM_DESCRIPTIONS["per_message_char_cap"])] = 800,
    ) -> dict[str, Any]:
        """Recall what was said in any past session — yours and the user's.

        This is your long-term memory. Your active context only holds
        the current session (and even that gets compacted as it grows).
        Everything the user told you, every answer you gave, every
        tool result you saw across every previous session lives in
        this index. Reach for this tool whenever you can't see
        something in your active context but suspect it happened.

        CALL THIS when the user says any of:
            • "remember…" / "do you remember…"
            • "last time" / "before" / "earlier" / "previously"
            • "what did I ask about…" / "what did we decide…"
            • "the X I mentioned" / "that thing we worked on"
            • any reference to a prior conversation, decision,
              ticker, name, link, file, or fact you don't currently
              have in front of you

        Searchable content (the only things this matches):
            • user text the user typed
            • your own prose responses
            • tool result bodies (including full bodies of large
              tool results that spilled to disk)

        Pattern is a Rust-style regex (RE2 subset). For a name or
        ticker, plain text is enough: ``"AAPL"``, ``"(?i)stock"``,
        ``"deadline"``. See per-argument descriptions for inline
        flags and other options.

        Returns: dict with ``matches[]`` and ``total_matches``. Each
        match has ``session``, ``session_started_at`` and ``turn[]``
        of ``{role, content, is_hit?}`` entries. On invalid input or
        an unbound scope, returns ``{"error": "...", ...}`` instead
        of raising.
        """
        scope, owner, err = _resolve_injected_scope()
        if err:
            return err
        assert scope is not None and owner is not None

        err = _validate_pattern(pattern)
        if err:
            return err

        since_dt, err = _parse_iso(since, field="since")
        if err:
            return err
        until_dt, err = _parse_iso(until, field="until")
        if err:
            return err

        # Phase 1: sync the cache.
        try:
            sync_scope(
                scope,
                owner,
                session_filter=session,
                since=since_dt,
                until=until_dt,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("memory_tools: sync failed")
            return {"error": "sync_failed", "message": str(exc)}

        # Phase 2: locate. Regex flags are carried inline in the
        # pattern itself (see docstring), so we pass them off here.
        try:
            hits, _engine = locate(
                scope,
                owner,
                pattern,
                session_filter=session,
                role_filter=role,
                match_source=match_source,
                ignore_case=False,
                multiline=False,
                dotall=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("memory_tools: locate failed")
            return {"error": "locate_failed", "message": str(exc)}

        # Sort: most-recent session first, then ordinal asc.
        def _sort_key(h):
            ts = P.parse_session_started_at(h.session)
            return (-(ts.timestamp() if ts else 0), h.ordinal)

        hits.sort(key=_sort_key)

        total = len(hits)
        kept = hits[:max_matches]

        # Phase 3: enrich.
        enriched = enrich(
            kept,
            pattern=pattern,
            ignore_case=False,
            multiline=False,
            dotall=False,
            context=context,
            turn_char_cap=turn_char_cap,
            per_message_char_cap=per_message_char_cap,
        )

        out_matches: list[dict[str, Any]] = []
        for e, h in zip(enriched, kept, strict=True):
            ts = P.parse_session_started_at(h.session)
            entry: dict[str, Any] = {
                "session": h.session,
                "session_started_at": ts.isoformat() if ts else None,
            }
            if e.turn is not None:
                entry["turn"] = [
                    {
                        "role": tm.role,
                        "content": tm.content,
                        **({"is_hit": True} if tm.is_hit else {}),
                    }
                    for tm in e.turn
                ]
            out_matches.append(entry)

        return {
            "matches": out_matches,
            "total_matches": total,
        }


__all__ = ["register_search_messages"]
