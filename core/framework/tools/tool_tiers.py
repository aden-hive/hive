"""Generic eager/searchable tool tiering — the engine behind ``search_tools``.

Extracted from the queen-only machinery in ``queen_lifecycle_tools.py`` so
that WORKERS can run the same split: a small always-enabled (eager) toolset
whose full schemas ship in every request, plus a searchable tier that appears
only as one-line entries in the ``<searchable_tools>`` manifest until the
agent loads it via the ``search_tools`` tool.

Two pieces live here:

* :class:`ToolTierState` — a single-pool tier engine (allowlist gate, eager
  gate, memoized eager list for prompt-cache stability, promote/restore with
  sidecar persistence). ``QueenPhaseState`` keeps its own two-pool
  implementation for now; both satisfy the small provider protocol below.
* :func:`build_search_tools` — the ``search_tools`` Tool schema + handler,
  shared verbatim between the queen registration and the worker synthetic
  tool. It only needs a *provider* exposing::

      get_searchable_tools() -> list[Tool]
      get_current_tools() -> list[Tool]
      unregistered_allowlisted_names() -> set[str]
      promote_searched_tools(names: list[str]) -> list[str]
      tool_inventory() -> dict[str, list[str]]

  (``QueenPhaseState`` and :class:`ToolTierState` both qualify.)

Semantics contract (kept in lockstep with ``QueenPhaseState``):

* An EMPTY ``always_enabled_names`` disables the split — every allowed tool
  is eager. Fail-open, so a boot-time expansion failure never hides tools.
* ``get_current_tools()`` returns the SAME list object until something
  changes, so the tools JSON sent to the LLM is byte-identical
  turn-to-turn and the provider prompt cache stays warm.
* Promotion order is preserved and persisted so a resumed session rebuilds
  the exact same eager schema order.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _first_line(text: str, max_len: int = 160) -> str:
    """First non-empty line of ``text``, trimmed — for the searchable manifest.

    Tool descriptions can be multi-paragraph; the manifest only needs a one-
    line summary so the agent can decide whether to load the full schema.
    """
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line if len(line) <= max_len else line[: max_len - 1].rstrip() + "…"
    return ""


def _match_searchable_tools(query: str, searchable: list, limit: int = 5) -> list[str]:
    """Resolve a search query to tool names from the searchable set.

    Deterministic (no model in the loop — Rule 5): two forms supported.
      * ``select:a,b,c`` — load these exact names (those present in the set).
      * free text — token-overlap scored against each tool's name +
        description; returns up to ``limit`` best matches with >=1 token hit,
        ranked by score then name.
    """
    by_name = {t.name: t for t in searchable}
    q = (query or "").strip()
    if q.lower().startswith("select:"):
        wanted = [n.strip() for n in q[len("select:") :].split(",") if n.strip()]
        # Preserve caller order; dedupe; keep only names actually searchable.
        seen: set[str] = set()
        return [n for n in wanted if n in by_name and not (n in seen or seen.add(n))]
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", q.lower()) if tok]
    if not tokens:
        return []
    scored: list[tuple[int, str]] = []
    for t in searchable:
        haystack = f"{t.name} {getattr(t, 'description', '') or ''}".lower()
        score = sum(1 for tok in tokens if tok in haystack)
        if score:
            scored.append((score, t.name))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [name for _, name in scored[:limit]]


def _match_names(query: str, names: set[str]) -> list[str]:
    """Match a search query against a bare set of tool names (no descriptions).

    Mirrors :func:`_match_searchable_tools` resolution — ``select:a,b`` exact
    names, or free-text token overlap against the name — but over a plain name
    set. Used to detect when a query targets an allowlisted-but-unregistered tool
    (whose schema/description isn't loaded) so search_tools can report it honestly
    instead of "no such tool".
    """
    q = (query or "").strip()
    if not q or not names:
        return []
    if q.lower().startswith("select:"):
        wanted = [n.strip() for n in q[len("select:") :].split(",") if n.strip()]
        return [n for n in wanted if n in names]
    tokens = [tok for tok in re.split(r"[^a-z0-9]+", q.lower()) if tok]
    if not tokens:
        return []
    return [n for n in sorted(names) if any(tok in n.lower() for tok in tokens)]


@dataclass
class ToolTierState:
    """Eager/searchable split over a single tool pool (worker-facing).

    The single-pool sibling of ``QueenPhaseState``'s independent-phase
    machinery, with identical gate semantics (see module docstring).

    ``gateable_names`` plays the role of the queen's ``mcp_tool_names_all``:
    the set of names the tiering MAY defer. Names outside it (synthetics,
    structural framework tools) are always eager and always allowed —
    a stale keep-set can never disable them.
    """

    pool: list = field(default_factory=list)  # list[Tool] — everything the agent MAY use
    # Eager tier. EMPTY SET DISABLES THE SPLIT (everything eager, fail-open).
    always_enabled_names: set = field(default_factory=set)
    # Names the split may defer (queen analog: mcp_tool_names_all).
    gateable_names: set = field(default_factory=set)
    # Optional membership allowlist over gateable names (queen analog:
    # enabled_mcp_tools). ``None`` = allow all.
    enabled_allowlist: list[str] | None = None
    # Names promoted via ``search_tools``; order preserved for cache-stable
    # eager schemas across turns/resumes.
    loaded_tool_names: list[str] = field(default_factory=list)
    # Sidecar file persisting {"loaded_tools": [...]} across resumes.
    persist_path: Path | None = None

    _filtered_pool: list = field(default_factory=list)
    _eager_pool: list = field(default_factory=list)

    # ---- gates (same precedence as QueenPhaseState) ----------------------

    def passes_allowlist(self, name: str) -> bool:
        """Membership gate: may the agent use this tool at all?"""
        if name in self.always_enabled_names or name not in self.gateable_names:
            return True
        if self.enabled_allowlist is None:
            return True
        return name in self.enabled_allowlist

    def is_eager(self, name: str) -> bool:
        """Schema-presentation gate: full schema up front vs manifest entry."""
        if not self.always_enabled_names:
            return True
        return name in self.always_enabled_names or name not in self.gateable_names or name in self.loaded_tool_names

    # ---- memoized views --------------------------------------------------

    def rebuild(self) -> None:
        """Recompute the memoized allowed/eager lists.

        Call after mutating ``pool`` / ``always_enabled_names`` /
        ``gateable_names`` / ``enabled_allowlist`` / ``loaded_tool_names``.
        Memoization keeps ``get_current_tools()`` returning the same list
        object across turns so the LLM prompt cache stays warm.
        """
        if self.enabled_allowlist is not None and not self.gateable_names:
            logger.warning(
                "ToolTierState.rebuild: gateable_names is empty but allowlist has %d entries — allowlist cannot be applied.",
                len(self.enabled_allowlist),
            )
        self._filtered_pool = [t for t in self.pool if self.passes_allowlist(t.name)]
        self._eager_pool = [t for t in self._filtered_pool if self.is_eager(t.name)]
        logger.info(
            "ToolTierState.rebuild: always_enabled=%d, loaded=%d, gateable=%d, pool=%d -> allowed=%d, eager=%d",
            len(self.always_enabled_names),
            len(self.loaded_tool_names),
            len(self.gateable_names),
            len(self.pool),
            len(self._filtered_pool),
            len(self._eager_pool),
        )

    def get_current_tools(self) -> list:
        """The EAGER (callable) tools — what the LLM request advertises."""
        if not self._eager_pool and self.pool:
            self.rebuild()
        return self._eager_pool

    def get_searchable_tools(self) -> list:
        """Allowed-but-not-loaded tools — the manifest source."""
        if not self._filtered_pool and self.pool:
            self.rebuild()
        return [t for t in self._filtered_pool if not self.is_eager(t.name)]

    def searchable_names(self) -> set[str]:
        """Names currently in the searchable (advertised-not-loaded) tier."""
        return {t.name for t in self.get_searchable_tools()}

    def unregistered_allowlisted_names(self) -> set[str]:
        """Allowlisted names absent from the gateable set (server never booted)."""
        if not self.enabled_allowlist:
            return set()
        return {n for n in self.enabled_allowlist if n not in self.gateable_names}

    def tool_inventory(self) -> dict[str, list[str]]:
        """Describe this session without loading tools or probing credentials."""
        return {
            "loaded": sorted(t.name for t in self.get_current_tools()),
            "searchable": sorted(t.name for t in self.get_searchable_tools()),
            "disabled": sorted(t.name for t in self.pool if not self.passes_allowlist(t.name)),
            "unavailable": sorted(self.unregistered_allowlisted_names()),
        }

    # ---- promotion / persistence ----------------------------------------

    def promote_searched_tools(self, names: list[str]) -> list[str]:
        """Move searched tool names into the loaded (eager) set.

        Appends each new name (order preserved), persists, and rebuilds the
        memos so the next step sees the tools as callable. Returns only the
        newly loaded names.
        """
        newly: list[str] = []
        for name in names:
            if name not in self.loaded_tool_names:
                self.loaded_tool_names.append(name)
                newly.append(name)
        if newly:
            self.persist_loaded_tools()
            self.rebuild()
        return newly

    def restore_loaded_tools(self, persisted: list[str], registered_names: set[str]) -> None:
        """Heal-on-read: adopt previously-loaded names that are still valid."""
        self.loaded_tool_names = [n for n in persisted if n in registered_names and self.passes_allowlist(n)]

    def persist_loaded_tools(self) -> None:
        """Merge ``{"loaded_tools": [...]}`` into the sidecar file, best-effort."""
        if self.persist_path is None:
            return
        try:
            existing: dict = {}
            if self.persist_path.exists():
                try:
                    existing = json.loads(self.persist_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = {}
            updates = {"loaded_tools": list(self.loaded_tool_names)}
            if all(existing.get(k) == v for k, v in updates.items()):
                return
            existing.update(updates)
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text(json.dumps(existing), encoding="utf-8")
        except OSError:
            pass

    def load_persisted_tools(self) -> list[str]:
        """Read the persisted ``loaded_tools`` list, or ``[]``."""
        if self.persist_path is None or not self.persist_path.exists():
            return []
        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        loaded = data.get("loaded_tools")
        return [n for n in loaded if isinstance(n, str)] if isinstance(loaded, list) else []


def build_search_tools(provider: Any) -> tuple[Any, Any]:
    """Build the ``search_tools`` Tool schema + async handler over ``provider``.

    ``provider`` is any object satisfying the protocol in the module
    docstring (``QueenPhaseState`` or :class:`ToolTierState`). Returns
    ``(tool, handler)`` where ``handler`` is ``async (*, query, max_results)``
    — register with ``registry.register("search_tools", tool, lambda inputs:
    handler(**inputs))`` or dispatch directly for synthetic (worker) use.

    The Tool description is kept byte-identical to the original queen
    registration so existing queen prompts don't churn.
    """
    from framework.llm.provider import Tool

    async def search_tools(*, query: str, max_results: int = 5) -> str:
        if query.strip().lower() == "inventory":
            return json.dumps(
                {
                    **provider.tool_inventory(),
                    "note": (
                        "Current session configuration only. Loaded tools are callable; searchable tools need loading; "
                        "disabled tools are excluded by the allowlist; unavailable tools are configured but not registered. "
                        "This does not verify credentials or service connectivity."
                    ),
                }
            )
        searchable = provider.get_searchable_tools()
        # Names the agent asked for that ARE allowlisted but whose MCP server
        # failed to register this session. Report these as "configured but
        # temporarily unavailable" rather than "no such tool", so the agent
        # doesn't give up on a tool it actually has access to (the chart_render
        # "search_tools says it doesn't exist" bug).
        unavailable = _match_names(query, provider.unregistered_allowlisted_names())
        # Names the agent asked for that are ALREADY loaded and callable this
        # session (loaded earlier via search_tools, or always-on). A loaded
        # tool is promoted out of the searchable set, so re-searching it would
        # otherwise fall through to "no searchable tool matched" — which reads
        # as "the tool doesn't exist" and sent at least one queen into a loop
        # of terminal_exec workarounds instead of just calling chart_render.
        # Report it as already-loaded so the agent invokes it directly.
        already_loaded = _match_names(query, {t.name for t in provider.get_current_tools()})
        already_loaded_note = (
            f"{', '.join(already_loaded)} is already loaded and callable right now — "
            "invoke it directly on your next step. No search_tools call is needed."
        )
        if not searchable:
            if already_loaded:
                return json.dumps(
                    {
                        "loaded": [],
                        "already_loaded": already_loaded,
                        "note": already_loaded_note,
                    }
                )
            if unavailable:
                return json.dumps(
                    {
                        "loaded": [],
                        "unavailable": unavailable,
                        "note": (
                            f"{', '.join(unavailable)} is configured but unavailable: it was not registered "
                            "in this session. Check runtime configuration, credentials, and server status. "
                            "Every other allowed tool is already loaded."
                        ),
                    }
                )
            return json.dumps(
                {
                    "loaded": [],
                    "note": ("Nothing to load — every tool you are allowed to use is already loaded."),
                }
            )
        try:
            limit = max(1, int(max_results))
        except (TypeError, ValueError):
            limit = 5
        matches = _match_searchable_tools(query, searchable, limit=limit)
        if not matches:
            available = ", ".join(sorted(t.name for t in searchable))
            if already_loaded:
                return json.dumps(
                    {
                        "loaded": [],
                        "already_loaded": already_loaded,
                        "note": already_loaded_note,
                    }
                )
            if unavailable:
                return json.dumps(
                    {
                        "loaded": [],
                        "unavailable": unavailable,
                        "note": (
                            f"{', '.join(unavailable)} is configured but unavailable: it was not registered "
                            "in this session. Check runtime configuration, credentials, and server status. "
                            f"Other searchable tools: {available}."
                        ),
                    }
                )
            return json.dumps(
                {
                    "loaded": [],
                    "note": (
                        f"No searchable tool matched {query!r}. Searchable tools: {available}. "
                        'Retry with different keywords or search_tools(query="select:exact_name").'
                    ),
                }
            )
        by_name = {t.name: t for t in searchable}
        loaded = provider.promote_searched_tools(matches)
        already = [n for n in matches if n not in loaded]
        return json.dumps(
            {
                "loaded": loaded,
                "already_loaded": already,
                "tools": [{"name": n, "description": _first_line(getattr(by_name.get(n), "description", "") or "")} for n in matches],
                "note": ("Loaded. These tools are callable from your next step and stay loaded for the rest of this session."),
            }
        )

    tool = Tool(
        name="search_tools",
        description=(
            "Loads tool schemas so you can call them. Tools in the "
            "<searchable_tools> block of your system prompt are listed by name only — "
            "their schemas are not loaded, so they cannot be called until you load them "
            "here. Once loaded, a tool is callable on your next step exactly like an "
            "always-on tool, and stays loaded for the rest of the session.\n\n"
            "Query forms:\n"
            '- "inventory" — report loaded, searchable, disabled, and unavailable tools without loading anything. '
            "Use before describing your capabilities.\n"
            '- "select:name_a,name_b" — load these exact tools by name (no limit). '
            "Preferred: the <searchable_tools> list already gives you the names, so pass "
            "all the ones this task needs in a single call.\n"
            '- "send gmail email" — keyword search; loads up to max_results best matches.'
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": ('"select:name_a,name_b" to load exact tools by name, or keywords to search.'),
                },
                "max_results": {
                    "type": "number",
                    "description": ("Max tools a keyword search loads (default 5). Ignored by select:, which loads every name you pass."),
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    )
    return tool, search_tools
