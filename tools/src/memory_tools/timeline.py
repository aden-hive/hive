"""``search_timeline``: the dated events, facts and plans a user has mentioned.

Reads the per-session ``timeline.jsonl`` files the host extracts
(``framework.agents.queen.timeline``) — one item per event, fact or plan,
with the date range it happened or held, resolved from the session date.
Answers the questions raw-transcript search is bad at: when something
happened, how many times, what changed and what is current.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from memory_tools import paths as P

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from fastmcp import FastMCP

TIMELINE_FILE = "timeline.jsonl"

_PARAM_DESCRIPTIONS = {
    "pattern": (
        "Regex matched case-insensitively against each item's text and its alias phrasings, e.g. 'wedding', "
        "'bak(e|ing)|cake|bread', 'museum'. Use '.' to list everything in a date range."
    ),
    "since": "ISO date. Only items that happened (or held) on or after this date.",
    "until": "ISO date. Only items that happened (or held) before this date (exclusive).",
    "kind": "'event' (happened), 'fact' (a state or preference as of a date), 'plan' (intended), or 'all' (default).",
    "max_results": "Cap on returned items. Default 60.",
}


def _overlaps(item: dict[str, Any], since: date | None, until: date | None) -> bool:
    start, end = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
    if since is not None and end < since:
        return False
    return not (until is not None and start >= until)


def search(
    scope: P.Scope,
    owner: str,
    pattern: str,
    *,
    since: date | None = None,
    until: date | None = None,
    kind: str = "all",
    max_results: int = 60,
) -> dict[str, Any]:
    """Matching timeline items across the owner's sessions, oldest first."""
    regex = re.compile(pattern, re.IGNORECASE)
    items: list[dict[str, Any]] = []
    sessions_with_timeline = 0
    for root in P.session_roots(scope, owner):
        if not root.is_dir():
            continue
        for session_dir in root.iterdir():
            path = session_dir / TIMELINE_FILE
            if not path.is_file():
                continue
            sessions_with_timeline += 1
            started = P.parse_session_started_at(session_dir.name)
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if kind != "all" and item.get("kind") != kind:
                    continue
                haystack = " | ".join([item.get("text", ""), *item.get("aliases", [])])
                if not regex.search(haystack):
                    continue
                try:
                    if not _overlaps(item, since, until):
                        continue
                except (KeyError, ValueError):
                    continue
                items.append(
                    {
                        "when": item["start"] if item["start"] == item["end"] else f"{item['start']}..{item['end']}",
                        "kind": item.get("kind", "event"),
                        "text": item.get("text", ""),
                        "said_on": f"{started:%Y-%m-%d}" if started else None,
                        "session": session_dir.name,
                        "turn": item.get("turn"),
                    }
                )
    items.sort(key=lambda i: (i["when"], i["said_on"] or "", i["session"], i["turn"] or 0))
    return {
        "items": items[:max_results],
        "total": len(items),
        "truncated": len(items) > max_results,
        "sessions_with_timeline": sessions_with_timeline,
    }


def register_search_timeline(mcp: FastMCP, scope_env: Callable[[], Mapping[str, str]] | None = None) -> None:
    @mcp.tool()
    def search_timeline(
        pattern: Annotated[str, Field(description=_PARAM_DESCRIPTIONS["pattern"])],
        since: Annotated[str | None, Field(description=_PARAM_DESCRIPTIONS["since"])] = None,
        until: Annotated[str | None, Field(description=_PARAM_DESCRIPTIONS["until"])] = None,
        kind: Annotated[Literal["event", "fact", "plan", "all"], Field(description=_PARAM_DESCRIPTIONS["kind"])] = "all",
        max_results: Annotated[int, Field(description=_PARAM_DESCRIPTIONS["max_results"])] = 60,
    ) -> dict:
        """Search the dated timeline of events, facts and plans the user has mentioned across past conversations.

        Each item is one occurrence, dated to when it happened or held (relative dates like "last week" are
        already resolved), with "said_on" for when the user mentioned it and the session/turn to open with
        search_messages for the full context. Results are oldest first.

        Use it for when / how many / how much / what changed / what is current questions: count distinct
        items in the asked window by their "when", take the latest fact for current state, and compare dates for
        before/after. Use search_messages for exact wording or anything the user didn't state as a fact.
        """
        from memory_tools.tool import _parse_iso, _resolve_injected_scope

        scope, owner, err = _resolve_injected_scope(scope_env() if scope_env else None)
        if err:
            return err
        assert scope is not None and owner is not None
        try:
            re.compile(pattern)
        except re.error as exc:
            return {"error": "pattern_invalid", "message": str(exc)}
        since_dt, err = _parse_iso(since, field="since")
        if err:
            return err
        until_dt, err = _parse_iso(until, field="until")
        if err:
            return err
        return search(
            scope,
            owner,
            pattern,
            since=since_dt.date() if since_dt else None,
            until=until_dt.date() if until_dt else None,
            kind=kind,
            max_results=max(1, min(max_results, 300)),
        )
