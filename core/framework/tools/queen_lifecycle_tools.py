"""Queen lifecycle tools for colony management.

These tools give the Queen agent control over colony workers.
They close over a session-like object, allowing late-binding access to
the colony runtime (which may be loaded/unloaded dynamically).

Usage::

    from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

    register_queen_lifecycle_tools(
        registry=queen_tool_registry,
        session=session,
        session_id=session.id,
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.credentials.models import CredentialError
from framework.host.event_bus import AgentEvent, EventType
from framework.loader.preload_validation import credential_errors_to_json

if TYPE_CHECKING:
    from framework.host.agent_host import AgentHost
    from framework.host.event_bus import EventBus
    from framework.loader.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)

# The queen's stop_worker tool runs as a normal tool call, so it is bound by
# ``tool_call_timeout_seconds`` (default 60s, see agent_loop/internals/types.py).
# The old default grace of 60s meant the graceful-report wait *always* hit that
# ceiling: the tool was declared timed-out, the queen saw an error, retried, and
# looped (seen in the wild: 37 consecutive stop_worker calls). Cap the grace well
# under the budget so the tool always returns cleanly, and back it with the
# authoritative bounded stop so "stopped" is true even if no one reported in time.
_DEFAULT_STOP_GRACE_SEC = 12.0
_MAX_STOP_GRACE_SEC = 25.0


# Matcher/manifest helpers moved to framework.tools.tool_tiers so the worker
# tiering path shares them. Re-exported here because existing tests and call
# sites import them from this module.
from framework.tools.tool_tiers import (  # noqa: E402, F401  (re-export)
    _first_line,
    _match_names,
    _match_searchable_tools,
    build_search_tools,
)


def _render_credentials_block(provider: Any) -> str:
    """Call a credentials_prompt_provider safely and return its output.

    Returns "" if no provider is set or if it raises (the Queen prompt must
    never fail to render because credential discovery hit a hiccup).
    """
    if provider is None:
        return ""
    try:
        result = provider()
    except Exception:
        logger.debug("credentials_prompt_provider raised", exc_info=True)
        return ""
    return result or ""


# Same shape as the colony id validators in routes_colonies / routes_sessions —
# lowercase alphanumeric and underscores only.
_COLONY_NAME_RE = re.compile(r"^[a-z0-9_]+$")


QUEEN_PHASES: frozenset[str] = frozenset({"independent", "colony"})

# Legacy phase names. Read paths (meta.json on disk, request bodies from
# older clients) normalise these via :func:`normalize_legacy_phase`.
# ``incubating`` was an intermediate state in the old start_incubating_colony
# → create_colony flow; the new flow forks via the frontend popup, so any
# pre-fork session that was persisted in incubating phase is treated as
# independent on resume.
_LEGACY_PHASE_ALIASES: dict[str, str] = {
    "working": "colony",
    "reviewing": "colony",
    "incubating": "independent",
}


def normalize_legacy_phase(phase: str | None) -> str | None:
    """Translate legacy phase strings to their current equivalents.

    Used on read paths (meta.json, request bodies) so persisted sessions
    written before the WORKING/REVIEWING merge still load. Pass-through
    for current names and ``None``.
    """
    if phase is None:
        return None
    return _LEGACY_PHASE_ALIASES.get(phase, phase)


@dataclass
class QueenPhaseState:
    """Mutable state container for queen operating phase.

    Two phases: independent, colony.
    INDEPENDENT: queen acts as a standalone agent with MCP tools, no colony workers.
        Calls ``suggest_colony`` when the user wants persistent / recurring /
        parallel work; the frontend drives the actual fork via POST
        /api/sessions.
    COLONY: the colony has been forked. Workers may be running, finished, or
        somewhere in between; the queen monitors, intervenes, summarises,
        and fans out follow-up runs as needed.

    Shared between the dynamic_tools_provider callback and tool handlers
    that trigger phase transitions.
    """

    phase: str = "independent"  # one of QUEEN_PHASES
    independent_tools: list = field(default_factory=list)  # list[Tool]
    colony_tools: list = field(default_factory=list)  # list[Tool]
    inject_notification: Any = None  # async (str) -> None
    event_bus: Any = None  # EventBus — for emitting QUEEN_PHASE_CHANGED events

    # Path to the queen session's meta.json. When set, every phase
    # transition merges {"phase": <new>} into it so cold-resume always
    # has a canonical answer without inferring from events.jsonl or
    # other indirect signals.
    meta_path: Path | None = None

    # Agent path — set after colony bootstrap so the frontend can query credentials
    agent_path: str | None = None

    # Phase-specific prompts (set by queen_orchestrator after construction)
    prompt_independent: str = ""
    prompt_colony: str = ""

    # Default skill operational protocols — appended to every phase prompt
    protocols_prompt: str = ""
    # Community skills catalog (XML) — appended after protocols
    skills_catalog_prompt: str = ""
    # Optional SkillsManager reference. When set, get_current_prompt()
    # re-renders the catalog filtered by the current phase so skills
    # whose frontmatter `visibility` list excludes this phase are
    # dropped (shaves ~1 KB of DM-irrelevant framework skills on
    # independent-phase turns).
    skills_manager: Any = None

    # Provider for the ambient "Connected integrations" block. The orchestrator
    # wires this to a function that snapshots CredentialStoreAdapter accounts
    # and renders them via build_accounts_prompt(). Called on every prompt
    # rebuild so newly added/deleted credentials show up without restart.
    credentials_prompt_provider: Any = None  # Callable[[], str] | None

    # Queen identity (set once at session start by queen identity hook,
    # persisted here so it survives dynamic prompt refreshes across iterations).
    queen_id: str | None = None
    queen_profile: dict | None = None
    queen_identity_prompt: str = ""

    # Cached recall blocks — populated async by recall_selector after each turn.
    # Delivered to the queen as a <system-reminder> riding the conversation
    # (see queen_orchestrator's recall injection), NOT via the system prompt:
    # anything that changes per turn in the system prompt sits before the
    # whole message history in the request and would invalidate the history
    # prefix cache on every change.
    _cached_global_recall_block: str = ""
    _cached_queen_recall_block: str = ""
    # Memory directories.
    global_memory_dir: Path | None = None
    queen_memory_dir: Path | None = None

    # Per-queen MCP tool allowlist for the INDEPENDENT phase. ``None`` means
    # "allow every MCP tool" (default, backward-compatible). An explicit list
    # is authoritative: only tools whose name appears here pass through.
    # Lifecycle / synthetic tools bypass this gate regardless.
    enabled_mcp_tools: list[str] | None = None
    # Union of every MCP-origin tool name currently registered — the set the
    # allowlist can gate. Populated once at queen boot from
    # ``ToolRegistry._mcp_server_tools``. Names outside this set (lifecycle,
    # ``ask_user``) always pass through the filter.
    mcp_tool_names_all: set = field(default_factory=set)
    # Memoized output of the allowlist filter applied to ``independent_tools``
    # (membership: every tool the queen MAY use). Recomputed only when
    # ``enabled_mcp_tools`` / ``independent_tools`` / ``loaded_tool_names``
    # change. The searchable manifest is rendered from this set.
    _filtered_independent_tools: list = field(default_factory=list)

    # ----- Always-enabled / searchable split (schema presentation) --------
    # Empty ``always_enabled_names`` disables the split: every allowed tool is
    # eager, preserving older boot/test paths.
    always_enabled_names: set = field(default_factory=set)
    # Searchable tool names loaded via ``search_tools``; order is persisted for
    # cache-stable eager schemas across turns/resumes.
    loaded_tool_names: list[str] = field(default_factory=list)
    # Memoized eager sublist returned to the LLM in independent phase.
    _eager_independent_tools: list = field(default_factory=list)

    async def switch_to_colony(self, source: str = "tool") -> None:
        """Switch to colony phase — the colony has been forked.

        Workers may be live or finished; the colony phase covers both states
        with a single tool surface and prompt. Replaces the prior
        ``switch_to_working`` / ``switch_to_reviewing`` split.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "colony":
            return
        self.phase = "colony"
        self.persist_phase()
        tool_names = [t.name for t in self.colony_tools]
        logger.info("Queen phase → colony (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to COLONY phase. "
                "The colony is live; monitor, intervene, and review as needed. "
                "Available tools: " + ", ".join(tool_names) + "."
            )

    def _passes_allowlist(self, name: str) -> bool:
        """Membership gate: may the queen use this tool at all?

        Single source of truth for the allowlist, shared by both phases.
        Precedence (checked BEFORE the allowlist): always-enabled tools and
        non-MCP tools (lifecycle / synthetic / ``ask_user``) always pass — a
        stale or restrictive sidecar can never disable them. Otherwise an MCP
        tool passes iff the allowlist is unset (allow-all) or names it.
        """
        if name in self.always_enabled_names or name not in self.mcp_tool_names_all:
            return True
        if self.enabled_mcp_tools is None:
            return True
        return name in self.enabled_mcp_tools

    def _is_eager(self, name: str) -> bool:
        """Schema-presentation gate: full schema up front vs searchable manifest.

        Eager: always-enabled, non-MCP (lifecycle/synthetic), or already loaded
        via ``search_tools`` this session. Everything else allowed is
        searchable. When ``always_enabled_names`` is empty the split is
        disabled and every allowed tool is eager — backward-compatible and
        fail-open, so a boot-time expansion failure never hides tools.
        """
        if not self.always_enabled_names:
            return True
        return name in self.always_enabled_names or name not in self.mcp_tool_names_all or name in self.loaded_tool_names

    def rebuild_independent_filter(self) -> None:
        """Recompute the memoized independent-phase tool lists.

        Called once at queen boot (after ``independent_tools``,
        ``mcp_tool_names_all``, ``enabled_mcp_tools``, ``always_enabled_names``
        and ``loaded_tool_names`` are populated), from the tools-PATCH handler
        when the allowlist changes, and from ``promote_searched_tools`` when a
        search loads a tool. Memoizing means the independent-phase branch of
        ``get_current_tools()`` returns the same Python list object across
        turns, so the LLM prompt cache stays warm until something changes.
        """
        # If ``mcp_tool_names_all`` is empty while an allowlist is set, every
        # MCP tool falls through ``_passes_allowlist``'s "not MCP" branch and
        # the allowlist is silently ignored — a fail-open bug (symptom: a
        # role-restricted queen sees every MCP tool). Warn so the upstream
        # cause (boot didn't populate ``mcp_tool_names_all``) is visible.
        if self.enabled_mcp_tools is not None and not self.mcp_tool_names_all:
            logger.warning(
                "rebuild_independent_filter: mcp_tool_names_all is empty but "
                "allowlist has %d entries — allowlist cannot be applied. "
                "Check that queen boot populated phase_state.mcp_tool_names_all.",
                len(self.enabled_mcp_tools),
            )
        self._filtered_independent_tools = [t for t in self.independent_tools if self._passes_allowlist(t.name)]
        self._eager_independent_tools = [t for t in self._filtered_independent_tools if self._is_eager(t.name)]
        logger.info(
            "rebuild_independent_filter: allowlist=%s, always_enabled=%d, loaded=%d, mcp_names=%d, independent=%d -> allowed=%d, eager=%d",
            "none" if self.enabled_mcp_tools is None else len(self.enabled_mcp_tools),
            len(self.always_enabled_names),
            len(self.loaded_tool_names),
            len(self.mcp_tool_names_all),
            len(self.independent_tools),
            len(self._filtered_independent_tools),
            len(self._eager_independent_tools),
        )

    def _filter_mcp_tools_for_phase(self, tools: list) -> list:
        """Apply the allowlist membership gate (used for colony-phase tools)."""
        return [t for t in tools if self._passes_allowlist(t.name)]

    def _filtered_tools_for_current_phase(self) -> list:
        """The allowlist-filtered tool set (eager + searchable) for this phase."""
        if self.phase == "colony":
            return self._filter_mcp_tools_for_phase(self.colony_tools)
        if not self._filtered_independent_tools and self.independent_tools:
            # Safety net: first call in tests / paths that skipped boot rebuild.
            self.rebuild_independent_filter()
        return self._filtered_independent_tools

    def get_current_tools(self) -> list:
        """Return the EAGER (callable) tools for the current phase.

        Searchable tools are deliberately excluded — they reach the LLM only
        as one-line entries in the prompt manifest (see
        ``render_searchable_manifest``) until ``search_tools`` loads them.
        """
        if self.phase == "colony":
            return [t for t in self._filter_mcp_tools_for_phase(self.colony_tools) if self._is_eager(t.name)]
        # Independent: return the memoized eager list directly so the JSON
        # sent to the LLM is byte-identical turn-to-turn.
        if not self._eager_independent_tools and self.independent_tools:
            self.rebuild_independent_filter()
        return self._eager_independent_tools

    def get_searchable_tools(self) -> list:
        """Tools the queen MAY use but that are not loaded — manifest source."""
        return [t for t in self._filtered_tools_for_current_phase() if not self._is_eager(t.name)]

    def unregistered_allowlisted_names(self) -> set[str]:
        """Allowlisted tool names that no live MCP server registered this session.

        These are "configured but unavailable" — distinct from "no such tool".
        A tool lands here when its MCP server failed to register at boot, so its
        name never enters ``mcp_tool_names_all`` even though the per-queen
        allowlist still grants it. Drives the honest ``search_tools`` message so
        the agent doesn't conclude an allowlisted tool doesn't exist. Returns an
        empty set in allow-all mode (``enabled_mcp_tools is None``), where an
        unregistered name can't be told apart from a typo.
        """
        if not self.enabled_mcp_tools:
            return set()
        return {n for n in self.enabled_mcp_tools if n not in self.mcp_tool_names_all}

    def tool_inventory(self) -> dict[str, list[str]]:
        pool = self.colony_tools if self.phase == "colony" else self.independent_tools
        return {
            "loaded": sorted(t.name for t in self.get_current_tools()),
            "searchable": sorted(t.name for t in self.get_searchable_tools()),
            "disabled": sorted(t.name for t in pool if not self._passes_allowlist(t.name)),
            "unavailable": sorted(self.unregistered_allowlisted_names()),
        }

    def promote_searched_tools(self, names: list[str]) -> list[str]:
        """Move searched tool names into the loaded (eager) set.

        Appends each new name (preserving order for cache-stable prompts),
        persists the updated set to meta.json, and rebuilds the memoized eager
        list so the next turn sees the tools as callable. Returns the names
        that were newly loaded (already-loaded names are skipped).
        """
        newly: list[str] = []
        for name in names:
            if name not in self.loaded_tool_names:
                self.loaded_tool_names.append(name)
                newly.append(name)
        if newly:
            self.persist_loaded_tools()
            self.rebuild_independent_filter()
        return newly

    def restore_loaded_tools(self, persisted: list[str], registered_names: set[str]) -> None:
        """Heal-on-read: adopt previously-searched tools that are still valid.

        Called once at queen boot, AFTER ``always_enabled_names``,
        ``enabled_mcp_tools`` and ``mcp_tool_names_all`` are populated and
        BEFORE ``rebuild_independent_filter``. Drops any persisted name that is
        no longer registered (server uninstalled / tool removed) or no longer
        allowed (allowlist tightened) — fail-safe, same spirit as the bypass.
        """
        self.loaded_tool_names = [n for n in persisted if n in registered_names and self._passes_allowlist(n)]

    def render_skills_catalog(self) -> str:
        """Render the phase-filtered skills catalog (the ``<available_skills>``
        block with its own "cat the SKILL.md / follow it" header), or ``""``.

        Sourced from the live ``skills_manager`` when present so per-phase
        ``visibility`` filtering applies, else the cached catalog. Delivered to
        the queen as a ``<system-reminder>`` (see ``SkillsCatalogReminderSource``)
        rather than baked into the static prompt — so it rides the conversation
        near the latest turn and refreshes when colony skills are written.
        """
        if self.skills_manager is not None:
            try:
                return self.skills_manager.skills_catalog_prompt_for_phase(self.phase) or ""
            except Exception:
                return self.skills_catalog_prompt or ""
        return self.skills_catalog_prompt or ""

    def get_static_prompt(self) -> str:
        """Return the stable portion of the system prompt for the current phase.

        Includes identity, phase-role prompt, connected-integrations block, and
        default skill protocols. These change only on phase transition, queen
        identity selection, or when the user adds/removes an integration — rare
        events. Designed to be byte-stable across AgentLoop iterations within a
        single user turn so that Anthropic's prompt cache keeps this block warm.

        Three surfaces deliberately do NOT live here — they are delivered as
        ``<system-reminder>`` blocks, so they ride the conversation near the
        latest turn and refresh on change without touching the cached prefix:
          * the skills catalog (``render_skills_catalog`` →
            ``SkillsCatalogReminderSource``)
          * the searchable-tools manifest (``get_searchable_tools`` →
            ``SearchableToolsReminderSource``)
          * recalled memories (``render_recall_block`` →
            queen_orchestrator's recall injection)
        """
        if self.phase == "colony":
            base = self.prompt_colony
        else:
            base = self.prompt_independent

        parts = []
        if self.queen_identity_prompt:
            parts.append(self.queen_identity_prompt)
        parts.append(base)
        credentials_block = _render_credentials_block(self.credentials_prompt_provider)
        if credentials_block:
            parts.append(credentials_block)
        if self.protocols_prompt:
            parts.append(self.protocols_prompt)
        return "\n\n".join(parts)

    def render_recall_block(self) -> str:
        """Join the cached recall blocks into one deliverable block, or ``""``.

        Recall used to ride the system prompt as a per-turn dynamic suffix;
        that block sits before the entire message history in the request, so
        every recall refresh invalidated the cached history prefix. It is now
        injected into the conversation as a ``<system-reminder>`` (see
        queen_orchestrator's recall injection), which appends near the tail
        and leaves the cached prefix untouched. Timestamps moved out for the
        same reason — they ride each injected event as a
        ``[YYYY-MM-DD HH:MM TZ]`` prefix (see ``drain_injection_queue``).
        """
        parts: list[str] = []
        if self._cached_global_recall_block:
            parts.append(self._cached_global_recall_block)
        if self._cached_queen_recall_block:
            parts.append(self._cached_queen_recall_block)
        return "\n\n".join(parts)

    def get_current_prompt(self) -> str:
        """Return the current system prompt.

        Retained for backward compatibility (conversation persistence, debug
        dumps, the identity hook's initial prompt). Since recall moved into
        the conversation, this is just the static prompt — byte-stable
        within a phase so the provider's prompt cache stays warm.
        """
        return self.get_static_prompt()

    async def _emit_phase_event(self) -> None:
        """Publish a QUEEN_PHASE_CHANGED event so the frontend updates the tag."""
        if self.event_bus is not None:
            data: dict = {"phase": self.phase}
            if self.agent_path:
                data["agent_path"] = self.agent_path
            await self.event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_PHASE_CHANGED,
                    stream_id="queen",
                    data=data,
                )
            )

    def _persist_meta(self, updates: dict[str, Any]) -> None:
        """Merge session-scoped runtime state into meta.json."""
        if self.meta_path is None:
            return
        try:
            existing: dict = {}
            if self.meta_path.exists():
                try:
                    existing = json.loads(self.meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = {}
            if all(existing.get(k) == v for k, v in updates.items()):
                return
            existing.update(updates)
            self.meta_path.write_text(json.dumps(existing), encoding="utf-8")
        except OSError:
            pass

    def persist_phase(self) -> None:
        """Merge the current phase into meta.json on disk."""
        self._persist_meta({"phase": self.phase})

    def persist_loaded_tools(self) -> None:
        """Merge the searched-and-loaded tool names into meta.json."""
        self._persist_meta({"loaded_tools": list(self.loaded_tool_names)})

    def persist_crm_setup(self) -> None:
        """Mark this session as a CRM setup / configuration conversation.

        One-way: the label arrives once, on the create call the desktop's CRM
        doors make, and a resume sends no body at all — so the on-disk copy is
        what keeps a setup conversation identifiable across a restart.
        """
        self._persist_meta({"crm_setup": True})

    async def switch_to_independent(self, source: str = "tool") -> None:
        """Switch to independent phase — queen acts as standalone agent.

        Args:
            source: Who triggered the switch — "tool", "frontend", or "auto".
        """
        if self.phase == "independent":
            return
        self.phase = "independent"
        self.persist_phase()
        tool_names = [t.name for t in self.independent_tools]
        logger.info("Queen phase → independent (source=%s, tools: %s)", source, tool_names)
        await self._emit_phase_event()
        if self.inject_notification and source != "tool":
            await self.inject_notification(
                "[PHASE CHANGE] Switched to INDEPENDENT mode. "
                "You are the agent — execute the task directly. "
                "Available tools: " + ", ".join(tool_names) + "."
            )


def _read_agent_triggers_json(agent_path: Path) -> list[dict]:
    """Read triggers.json from the agent's export directory."""
    triggers_path = agent_path / "triggers.json"
    if not triggers_path.exists():
        return []
    try:
        data = json.loads(triggers_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write_agent_triggers_json(agent_path: Path, triggers: list[dict]) -> None:
    """Write triggers.json to the agent's export directory."""
    triggers_path = agent_path / "triggers.json"
    triggers_path.write_text(
        json.dumps(triggers, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _save_trigger_to_agent(session: Any, trigger_id: str, tdef: Any) -> None:
    """Persist a trigger definition to the agent's triggers.json."""
    agent_path = getattr(session, "worker_path", None)
    if agent_path is None:
        return
    triggers = _read_agent_triggers_json(agent_path)
    triggers = [t for t in triggers if t.get("id") != trigger_id]
    triggers.append(
        {
            "id": tdef.id,
            "name": tdef.description or tdef.id,
            "trigger_type": tdef.trigger_type,
            "trigger_config": tdef.trigger_config,
            "task": tdef.task or "",
            "enabled": bool(getattr(tdef, "enabled", False)),
            "last_fired_at": getattr(tdef, "last_fired_at", None),
            "next_due_at": getattr(tdef, "next_due_at", None),
        }
    )
    _write_agent_triggers_json(agent_path, triggers)
    logger.info("Saved trigger '%s' to %s/triggers.json", trigger_id, agent_path)


def _remove_trigger_from_agent(session: Any, trigger_id: str) -> None:
    """Remove a trigger definition from the agent's triggers.json."""
    agent_path = getattr(session, "worker_path", None)
    if agent_path is None:
        return
    triggers = _read_agent_triggers_json(agent_path)
    updated = [t for t in triggers if t.get("id") != trigger_id]
    if len(updated) != len(triggers):
        _write_agent_triggers_json(agent_path, updated)
        logger.info("Removed trigger '%s' from %s/triggers.json", trigger_id, agent_path)


async def _persist_active_triggers(session: Any, session_id: str) -> None:
    """Sync each trigger's ``active`` flag (and task) in the colony triggers.json.

    The colony's ``triggers.json`` is the single source of truth for both
    trigger definitions and their active status — there is no separate
    session-state store. ``session_id`` is accepted for signature
    compatibility but unused.
    """
    agent_path = getattr(session, "worker_path", None)
    if agent_path is None:
        return
    triggers = _read_agent_triggers_json(agent_path)
    if not triggers:
        return
    active_ids = set(getattr(session, "active_trigger_ids", set()) or set())
    available = getattr(session, "available_triggers", {}) or {}
    for entry in triggers:
        tid = entry.get("id", "")
        entry["enabled"] = tid in active_ids
        # Keep the persisted task in sync with any in-session override.
        tdef = available.get(tid)
        if tdef is not None and getattr(tdef, "task", None):
            entry["task"] = tdef.task
    try:
        _write_agent_triggers_json(agent_path, triggers)
    except OSError:
        logger.warning("Failed to persist active triggers to %s", agent_path, exc_info=True)


async def _emit_trigger_fired(session: Any, trigger_id: str, trigger_type: str) -> None:
    """Publish EventType.TRIGGER_FIRED and update per-session fire stats.

    Called by both the timer loop and the webhook handler right after
    ``queen_node.inject_trigger(...)``. The event carries refreshed
    ``next_fire_at``/``next_fire_in`` so the UI can re-anchor its
    countdown without polling, plus ``fire_count``/``last_fired_at`` for
    the "fired Nx · last 2m ago" badge.
    """
    now_wall = time.time()
    stats_map = getattr(session, "trigger_fire_stats", None)
    fire_count: int | None = None
    last_fired_at: int = int(now_wall * 1000)
    if stats_map is not None:
        s = stats_map.setdefault(trigger_id, {"fire_count": 0, "last_fired_at": None})
        s["fire_count"] = int(s.get("fire_count", 0)) + 1
        s["last_fired_at"] = last_fired_at
        fire_count = s["fire_count"]

    bus = getattr(session, "event_bus", None)
    if bus is None:
        return

    # Pull the task/description off the trigger definition so the chat
    # banner can render something human-readable without a second fetch.
    tdef = getattr(session, "available_triggers", {}).get(trigger_id)
    task_str = getattr(tdef, "task", "") or "" if tdef else ""
    name_str = getattr(tdef, "description", "") or trigger_id if tdef else trigger_id

    data: dict[str, Any] = {
        "trigger_id": trigger_id,
        "trigger_type": trigger_type,
        "name": name_str,
        "task": task_str,
        "last_fired_at": last_fired_at,
    }
    if fire_count is not None:
        data["fire_count"] = fire_count

    mono = getattr(session, "trigger_next_fire", {}).get(trigger_id)
    if mono is not None:
        remaining = max(0.0, mono - time.monotonic())
        data["next_fire_in"] = remaining
        data["next_fire_at"] = int((now_wall + remaining) * 1000)

    try:
        await bus.publish(AgentEvent(type=EventType.TRIGGER_FIRED, stream_id="queen", data=data))
    except Exception:
        logger.warning("Failed to publish TRIGGER_FIRED for '%s'", trigger_id, exc_info=True)


# ---------------------------------------------------------------------------
# Missed-trigger handshake
#
# Triggers don't fire while a colony's session is closed. On next load
# ``session_manager`` calls ``compute_missed`` (in
# ``framework.host.triggers``) to summarise the gap and emits a
# ``MISSED_TRIGGERS`` event. The UI's modal lets the user choose what
# to do for each missed trigger, then POSTs the decision map to
# ``/api/sessions/{id}/colony/resolve_missed`` which delegates here.
# ---------------------------------------------------------------------------


_MISSED_TRIGGER_DECISIONS = {"fire_latest", "skip", "reschedule"}


def _next_due_from(tdef: Any, anchor: datetime) -> str | None:
    """Compute the next future fire time for a trigger anchored at
    ``anchor``. Returns None if the schedule can't produce one
    (invalid config, webhook trigger, etc.)."""
    cfg = getattr(tdef, "trigger_config", {}) or {}
    cron_expr = cfg.get("cron")
    interval = cfg.get("interval_minutes")
    if cron_expr:
        try:
            from croniter import croniter

            return croniter(cron_expr, anchor).get_next(datetime).astimezone(UTC).isoformat()
        except Exception:
            return None
    if interval:
        try:
            return (anchor + timedelta(minutes=float(interval))).astimezone(UTC).isoformat()
        except (TypeError, ValueError):
            return None
    return None


async def _inject_catch_up(session: Any, trigger_id: str, tdef: Any) -> None:
    """Inject a one-shot catch-up ``TriggerEvent`` into the queen.

    The payload carries ``catch_up=True`` so the queen knows the fire
    was the user's explicit answer to a missed-trigger handshake and
    can compress workload for a single catch-up rather than running
    every missed tick.
    """
    from framework.agent_loop.agent_loop import TriggerEvent

    executor = getattr(session, "queen_executor", None)
    if executor is None:
        return
    queen_node = getattr(executor, "node_registry", {}).get("queen")
    if queen_node is None:
        return
    event = TriggerEvent(
        trigger_type=tdef.trigger_type,
        source_id=trigger_id,
        payload={
            "task": getattr(tdef, "task", "") or "",
            "trigger_config": getattr(tdef, "trigger_config", {}) or {},
            "catch_up": True,
        },
    )
    await queen_node.inject_trigger(event)


async def resolve_missed(
    session: Any,
    decisions: dict[str, str],
) -> dict[str, str]:
    """Apply the user's missed-trigger handshake decisions.

    ``decisions`` maps ``trigger_id`` → ``"fire_latest" | "skip" | "reschedule"``.

    - **fire_latest** — inject one catch-up trigger event; stamp
      ``last_fired_at = now`` so subsequent missed-math sees no gap.
    - **skip** — stamp ``last_fired_at = now`` without firing.
    - **reschedule** — stamp ``last_fired_at = now`` and recompute
      ``next_due_at`` from now. No fire.

    Returns a per-trigger result map (``"fired"``, ``"skipped"``,
    ``"rescheduled"``, ``"unknown_trigger"``, or
    ``"invalid_decision:<value>"``).
    """
    available = getattr(session, "available_triggers", {}) or {}
    results: dict[str, str] = {}
    now = datetime.now(tz=UTC)

    for tid, decision in decisions.items():
        if decision not in _MISSED_TRIGGER_DECISIONS:
            results[tid] = f"invalid_decision:{decision}"
            continue
        tdef = available.get(tid)
        if tdef is None:
            results[tid] = "unknown_trigger"
            continue

        next_due = _next_due_from(tdef, now)
        tdef.last_fired_at = now.isoformat()
        tdef.next_due_at = next_due
        try:
            _save_trigger_to_agent(session, tid, tdef)
        except Exception:
            logger.warning(
                "Failed to persist trigger '%s' after %s",
                tid,
                decision,
                exc_info=True,
            )

        if decision == "fire_latest":
            await _inject_catch_up(session, tid, tdef)
            try:
                await _emit_trigger_fired(session, tid, tdef.trigger_type)
            except Exception:
                logger.warning(
                    "Failed to emit TRIGGER_FIRED for catch-up '%s'",
                    tid,
                    exc_info=True,
                )
            results[tid] = "fired"
        elif decision == "skip":
            results[tid] = "skipped"
        else:  # reschedule
            results[tid] = "rescheduled"

    return results


async def _start_trigger_timer(session: Any, trigger_id: str, tdef: Any) -> None:
    """Start an asyncio background task that fires the trigger on a timer."""
    from framework.agent_loop.agent_loop import TriggerEvent

    cron_expr = tdef.trigger_config.get("cron")
    interval_minutes = tdef.trigger_config.get("interval_minutes")

    # Seed the first-fire time up front so introspection (and the UI
    # countdown) have a value immediately on activation instead of only
    # after the first tick. Cron uses croniter's next match; interval
    # uses interval_minutes. Both use monotonic, matching route readers.
    fire_times = getattr(session, "trigger_next_fire", None)
    if fire_times is not None:
        if cron_expr:
            try:
                from croniter import croniter as _croniter_seed

                _first = _croniter_seed(cron_expr, datetime.now(tz=UTC)).get_next(datetime)
                _first_delay = max(0.0, (_first - datetime.now(tz=UTC)).total_seconds())
            except Exception:
                _first_delay = 60.0
        else:
            _first_delay = float(interval_minutes) * 60 if interval_minutes else 60.0
        fire_times[trigger_id] = time.monotonic() + _first_delay

    async def _timer_loop() -> None:
        if cron_expr:
            from croniter import croniter

            cron = croniter(cron_expr, datetime.now(tz=UTC))

        while True:
            try:
                if cron_expr:
                    next_fire = cron.get_next(datetime)
                    delay = (next_fire - datetime.now(tz=UTC)).total_seconds()
                    if delay > 0:
                        await asyncio.sleep(delay)
                else:
                    await asyncio.sleep(float(interval_minutes) * 60)

                # Record the *subsequent* next-fire time for introspection.
                # For cron we peek one step further; for interval we add
                # another interval. Matches routes' monotonic clock.
                fire_times = getattr(session, "trigger_next_fire", None)
                if fire_times is not None:
                    if cron_expr:
                        try:
                            _peek = croniter(cron_expr, datetime.now(tz=UTC)).get_next(datetime)
                            _next_delay = max(0.0, (_peek - datetime.now(tz=UTC)).total_seconds())
                        except Exception:
                            _next_delay = 60.0
                    else:
                        _next_delay = float(interval_minutes) * 60 if interval_minutes else 60.0
                    fire_times[trigger_id] = time.monotonic() + _next_delay

                # Gate on a colony being bound to this session
                if getattr(session, "colony_id", None) is None:
                    continue

                # Fire into queen node
                executor = getattr(session, "queen_executor", None)
                if executor is None:
                    continue
                queen_node = getattr(executor, "node_registry", {}).get("queen")
                if queen_node is None:
                    continue

                event = TriggerEvent(
                    trigger_type="timer",
                    source_id=trigger_id,
                    payload={
                        "task": tdef.task or "",
                        "trigger_config": tdef.trigger_config,
                    },
                )
                await queen_node.inject_trigger(event)
                await _emit_trigger_fired(session, trigger_id, "timer")

                # Persist last_fired_at + next_due_at so the activation
                # missed-triggers handshake can reconstruct which ticks
                # would have fired during a deactivation gap. Done after
                # the fire (not before) so a crash mid-fire leaves the
                # previous timestamp intact.
                fire_dt = datetime.now(tz=UTC)
                tdef.last_fired_at = fire_dt.isoformat()
                if cron_expr:
                    try:
                        _peek_next = croniter(cron_expr, fire_dt).get_next(datetime)
                        tdef.next_due_at = _peek_next.isoformat()
                    except Exception:
                        tdef.next_due_at = None
                elif interval_minutes:
                    tdef.next_due_at = (fire_dt + timedelta(minutes=float(interval_minutes))).isoformat()
                try:
                    _save_trigger_to_agent(session, trigger_id, tdef)
                except Exception:
                    logger.warning(
                        "Failed to persist trigger fire timestamps for '%s'",
                        trigger_id,
                        exc_info=True,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Timer trigger '%s' tick failed", trigger_id, exc_info=True)

    task = asyncio.create_task(_timer_loop(), name=f"trigger_timer_{trigger_id}")
    if not hasattr(session, "active_timer_tasks"):
        session.active_timer_tasks = {}
    session.active_timer_tasks[trigger_id] = task


async def _start_trigger_webhook(session: Any, trigger_id: str, tdef: Any) -> None:
    """Subscribe to WEBHOOK_RECEIVED events and route matching ones to the queen."""
    from framework.agent_loop.agent_loop import TriggerEvent
    from framework.host.webhook_server import WebhookRoute, WebhookServer, WebhookServerConfig

    bus = session.event_bus
    path = tdef.trigger_config.get("path", "")
    methods = [m.upper() for m in tdef.trigger_config.get("methods", ["POST"])]

    async def _on_webhook(event: AgentEvent) -> None:
        data = event.data or {}
        if data.get("path") != path:
            return
        if data.get("method", "").upper() not in methods:
            return
        # Gate on a colony being bound to this session
        if getattr(session, "colony_id", None) is None:
            return
        executor = getattr(session, "queen_executor", None)
        if executor is None:
            return
        queen_node = getattr(executor, "node_registry", {}).get("queen")
        if queen_node is None:
            return

        trigger_event = TriggerEvent(
            trigger_type="webhook",
            source_id=trigger_id,
            payload={
                "task": tdef.task or "",
                "path": data.get("path", ""),
                "method": data.get("method", ""),
                "headers": data.get("headers", {}),
                "payload": data.get("payload", {}),
                "query_params": data.get("query_params", {}),
            },
        )
        await queen_node.inject_trigger(trigger_event)
        await _emit_trigger_fired(session, trigger_id, "webhook")

    sub_id = bus.subscribe(
        event_types=[EventType.WEBHOOK_RECEIVED],
        handler=_on_webhook,
        filter_stream=trigger_id,
    )
    if not hasattr(session, "active_webhook_subs"):
        session.active_webhook_subs = {}
    session.active_webhook_subs[trigger_id] = sub_id

    # Ensure the webhook HTTP server is running
    if getattr(session, "queen_webhook_server", None) is None:
        port = int(tdef.trigger_config.get("port", 8090))
        config = WebhookServerConfig(host="127.0.0.1", port=port)
        server = WebhookServer(bus, config)
        session.queen_webhook_server = server

    server = session.queen_webhook_server
    route = WebhookRoute(source_id=trigger_id, path=path, methods=methods)
    server.add_route(route)
    if not getattr(server, "is_running", False):
        await server.start()
        server.is_running = True


def register_queen_lifecycle_tools(
    registry: ToolRegistry,
    session: Any = None,
    session_id: str | None = None,
    # Server context — enables load_built_agent tool
    session_manager: Any = None,
    manager_session_id: str | None = None,
    # Mode switching
    phase_state: QueenPhaseState | None = None,
) -> int:
    """Register queen lifecycle tools.

    Args:
        session: Session-like object with a ``colony_runtime`` attribute.
            The tools read ``session.colony_runtime`` on each call,
            supporting late-binding.
        session_id: Shared session ID so the colony uses the same session
            scope as the queen and judge.
        session_manager: (Server only) The SessionManager instance, needed
            for ``load_built_agent`` to hot-load a colony.
        manager_session_id: (Server only) The session's ID in the manager.
        phase_state: (Optional) Mutable phase state for working/reviewing
            phase switching.

    Returns the number of tools registered.
    """
    if session is None:
        raise ValueError("session must be provided")

    from framework.llm.provider import Tool

    tools_registered = 0

    def _get_runtime():
        """Get current colony runtime from session (late-binding)."""
        return getattr(session, "colony_runtime", None)

    async def _publish_trigger_activated(trigger_id: str, trigger_type: str, trigger_config: dict, tdef: Any) -> None:
        bus = getattr(session, "event_bus", None)
        if not bus:
            return
        runner = getattr(session, "runner", None)
        graph_entry = runner.graph.entry_node if runner else None
        await bus.publish(
            AgentEvent(
                type=EventType.TRIGGER_ACTIVATED,
                stream_id="queen",
                data={
                    "trigger_id": trigger_id,
                    "trigger_type": trigger_type,
                    "trigger_config": trigger_config,
                    "name": tdef.description or trigger_id,
                    **({"entry_node": graph_entry} if graph_entry else {}),
                },
            )
        )

    # --- search_tools ----------------------------------------------------
    # On-demand loader for the searchable tool tier. The queen boots with a
    # small always-enabled toolset; everything else it is allowed to use is
    # searchable (name + one-line summary in the <searchable_tools> prompt
    # manifest) and must be loaded here before it can be called. Loads persist
    # to meta.json so a resumed session keeps them without re-searching.
    # Registered only when a phase_state is available (the searchable split
    # lives there); paths without one keep the full tool surface.
    if phase_state is not None:
        _search_tools_tool, _search_tools_handler = build_search_tools(phase_state)
        registry.register("search_tools", _search_tools_tool, lambda inputs: _search_tools_handler(**inputs))
        tools_registered += 1

    # ``start_worker`` was removed in the Phase 4 unification — its
    # bare-bones spawn duplicated ``run_agent_with_input`` (which has
    # credential preflight, concurrency guard, and phase tracking on
    # top). The shared preflight timeout below is used by both
    # ``run_agent_with_input`` and ``run_worker``.
    _START_PREFLIGHT_TIMEOUT = 15  # seconds

    async def _preflight_credentials(
        legacy: Any,
        *,
        tool_label: str,
    ) -> set[str]:
        """Compute tools whose credentials are missing and resync MCP servers.

        Shared between ``run_agent_with_input`` (single spawn) and
        ``run_worker`` (batch spawn). Returns the set of
        tool names whose credentials failed validation; the caller
        filters these out of the spawn's tool lists.

        Exceptions (including validator bugs) are logged and treated
        as "no tools dropped" so a broken validator can't block a
        spawn. Wall-clock bound at ``_START_PREFLIGHT_TIMEOUT`` —
        slow credential HTTP health checks can't stall the LLM turn.
        """
        unavailable: set[str] = set()

        async def _run() -> None:
            nonlocal unavailable
            try:
                from framework.credentials.validation import compute_unavailable_tools

                loop = asyncio.get_running_loop()
                drop, messages = await loop.run_in_executor(
                    None,
                    lambda: compute_unavailable_tools(legacy.graph.nodes),
                )
                unavailable = drop
                if drop:
                    logger.warning(
                        "%s: dropping %d tool(s) with unavailable credentials: %s",
                        tool_label,
                        len(drop),
                        "; ".join(messages),
                    )
            except Exception as exc:
                logger.warning(
                    "%s: compute_unavailable_tools raised, proceeding without credential-based tool filtering: %s",
                    tool_label,
                    exc,
                )

            runner = getattr(session, "runner", None)
            if runner is not None:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: runner._tool_registry.resync_mcp_servers_if_needed(),
                    )
                except Exception as exc:
                    logger.warning("%s: MCP resync failed: %s", tool_label, exc)

        try:
            await asyncio.wait_for(_run(), timeout=_START_PREFLIGHT_TIMEOUT)
        except TimeoutError:
            logger.warning(
                "%s: credential preflight timed out after %ds — proceeding",
                tool_label,
                _START_PREFLIGHT_TIMEOUT,
            )
        return unavailable

    # --- stop_worker -----------------------------------------------------------

    async def stop_worker(
        *,
        reason: str = "Stopped by queen",
        grace_seconds: float = _DEFAULT_STOP_GRACE_SEC,
    ) -> str:
        """Stop all active colony workers, giving them a brief window to report.

        Each live worker first receives a ``[STOP REQUESTED]`` inject asking it
        to call ``report_to_parent`` with whatever partial progress it has. We
        block for up to ``grace_seconds`` collecting those reports, then run the
        authoritative hard stop (``colony.stop_workers``) which guarantees every
        worker — live laggards AND queued ones — ends terminal, concurrently and
        each on its own timeout.

        ``grace_seconds`` is clamped to ``[0, _MAX_STOP_GRACE_SEC]``: this tool is
        bound by the 60s tool-call budget, and a longer wait would time the whole
        tool out and make the queen think the stop failed (then retry, and loop).
        ``0`` skips the report wait and hard-stops immediately.

        The collected reports are returned so the queen can summarise what
        happened in the same turn.
        """
        colony = getattr(session, "colony", None)
        legacy = _get_runtime()

        if colony is None and legacy is None:
            return json.dumps({"error": "No runtime on this session."})

        reports: list[dict[str, Any]] = []
        live_ids: list[str] = []
        queued_ids: list[str] = []
        errors: list[str] = []
        playbooks_stopped: list[str] = []

        if colony is not None:
            # Cancel any running playbook convergence loops FIRST. Otherwise the
            # loop just re-dispatches fresh workers for every still-pending row
            # the moment we stop the current batch, and the queen's "all workers
            # stopped" report is false — the job keeps going. Done before the
            # worker snapshot so no new worker can slip into `live_ids` behind us.
            try:
                from framework.tools.playbook_tools import stop_playbooks_for_colony

                playbooks_stopped = await stop_playbooks_for_colony(colony)
            except Exception as e:
                errors.append(f"stop_playbooks: {e}")
                logger.warning(
                    "stop_worker: failed to cancel running playbooks",
                    exc_info=True,
                )

            try:
                # Snapshot live worker ids BEFORE injecting — wait_for_worker_reports
                # / stop_all_workers mutate the registry, so we need a stable list
                # to report on.
                snapshot = colony.list_workers()
                # Queued workers haven't started their loop, so there's nothing to
                # report — and leaving them would let them run the moment capacity
                # frees (including capacity this very stop frees). Hard-stop them
                # now rather than feeding them into the grace wait below, where
                # they'd never report and would pin it open for the full window.
                queued_ids = [info.id for info in snapshot if info.status.value == "queued"]
                live_ids = [info.id for info in snapshot if info.status.value in ("pending", "running")]

                # Suppress the orchestrator's duplicate [WORKER_REPORT] inject for
                # every worker we're stopping — queued ones have nothing to report,
                # and live ones' reports are returned synchronously below. The
                # actual stop of the queued workers is handled by the single
                # `colony.stop_workers()` call at the end (bounded + concurrent).
                if queued_ids or live_ids:
                    claimed = getattr(colony, "_suppress_report_inject_for", None)
                    if claimed is None:
                        claimed = set()
                        try:
                            colony._suppress_report_inject_for = claimed
                        except AttributeError:
                            claimed = None
                    if claimed is not None:
                        claimed.update(queued_ids)
                        claimed.update(live_ids)

                # Clamp the grace window under the tool-call budget (see the
                # module constants) so this tool always returns cleanly instead
                # of timing out and triggering a retry loop.
                grace = min(max(0.0, grace_seconds), _MAX_STOP_GRACE_SEC)

                if live_ids and grace > 0:
                    # Give live workers a brief chance to report partial progress
                    # before the hard stop. Best-effort — the guaranteed stop is
                    # the stop_workers() call below, so a slow/missed report never
                    # leaves a worker running.
                    stop_msg = (
                        f"[STOP REQUESTED] {reason}. Call report_to_parent "
                        "immediately with your latest progress, decisions, "
                        "and partial findings. You have "
                        f"~{grace:.0f}s before a hard stop — anything not "
                        "reported by then will be lost."
                    )
                    for wid in live_ids:
                        worker = colony.get_worker(wid)
                        if worker is None or not worker.is_active:
                            continue
                        # Worker may have just filed a report on its own;
                        # don't nudge a finished worker into emitting a
                        # redundant turn.
                        if getattr(worker, "_explicit_report", None) is not None:
                            continue
                        try:
                            await colony.send_to_worker(wid, stop_msg)
                        except Exception:
                            logger.warning(
                                "stop_worker: stop-inject failed for %s",
                                wid,
                                exc_info=True,
                            )

                    # Blocks until each id reports OR the deadline hits; on
                    # timeout the helper force-stops the laggard and synthesises a
                    # ``status="timeout"`` entry, so every id appears in the list.
                    reports = await colony.wait_for_worker_reports(live_ids, timeout=grace)

                # Authoritative hard stop for EVERYTHING non-persistent — queued
                # workers, any live laggard that ignored the grace inject, and
                # anything spawned in the gap. Concurrent + per-worker bounded, and
                # it spares the persistent overseer (the queen herself). Replaces
                # the old grace=0 `stop_all_workers()` path (which cleared the
                # registry and would have stopped the queen too).
                stop_summary = await colony.stop_workers()
                if stop_summary.get("timed_out"):
                    errors.append(f"force-stopped (unresponsive): {stop_summary['timed_out']}")
            except Exception as e:
                errors.append(f"unified: {e}")
                logger.warning(
                    "stop_worker: failed to stop unified colony workers",
                    exc_info=True,
                )

        # Workers themselves live on the unified ColonyRuntime above; the
        # queen's own AgentHost runtime is kept only for timer-based triggers,
        # so this branch is just "pause the cron timers".
        timers_paused = False
        if legacy is not None:
            try:
                legacy.pause_timers()
                timers_paused = True
            except Exception as e:
                errors.append(f"pause_timers: {e}")
                logger.warning(
                    "stop_worker: pause_timers failed",
                    exc_info=True,
                )

        total_workers_stopped = len(live_ids) + len(queued_ids)
        logger.info(
            "stop_worker: stopped %d worker(s) (%d queued), cancelled %d playbook(s), %d report(s) collected. reason=%s",
            total_workers_stopped,
            len(queued_ids),
            len(playbooks_stopped),
            len(reports),
            reason,
        )

        return json.dumps(
            {
                # "stopped" whenever we actually halted something — workers (live
                # or queued) OR a playbook loop that would otherwise keep dispatching.
                "status": "stopped" if (total_workers_stopped or playbooks_stopped) else "no_active_workers",
                "workers_stopped": total_workers_stopped,
                "queued_stopped": len(queued_ids),
                "playbooks_stopped": playbooks_stopped,
                "reports": reports,
                "timers_paused": timers_paused,
                "reason": reason,
                "errors": errors if errors else None,
            }
        )

    _stop_tool = Tool(
        name="stop_worker",
        description=(
            "Halt ALL colony work and pause timers. Use this whenever the user "
            "asks to pause, stop, or halt — it is the honest 'stop everything'. "
            "It first cancels any running playbook convergence loops (so they "
            "can't re-dispatch fresh workers), then cancels every active worker "
            "— including queued ones waiting for capacity. Each live worker "
            "first receives a [STOP REQUESTED] inject asking it to call "
            "report_to_parent with its latest progress; workers that do not "
            "report within `grace_seconds` are force-stopped. This is reliable "
            "and fast — it always returns within seconds, so call it ONCE and "
            "report the result; do not retry it in a loop. The collected reports "
            "plus the list of cancelled playbooks are returned in the tool "
            "result, so report what ACTUALLY stopped from that result — do not "
            "claim everything is stopped without it. Leave `grace_seconds` "
            "unset for a short reporting window; pass 0 for an immediate hard "
            "stop.\n"
            "To halt one specific run_playbook run while leaving others going, "
            "use stop_playbook(run_id=...) instead."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Why the workers are being stopped. Surfaced to "
                        "each worker in the stop inject so its final "
                        "report_to_parent call can reflect the cause."
                    ),
                },
                "grace_seconds": {
                    "type": "number",
                    "description": (
                        "Seconds to wait for workers to file a "
                        "report_to_parent before force-stopping. Clamped to "
                        "[0, 25]; leave unset for a short window, or 0 for an "
                        "immediate hard stop."
                    ),
                },
            },
            "required": [],
        },
    )
    registry.register(
        "stop_worker",
        _stop_tool,
        lambda inputs: stop_worker(**inputs),
    )
    tools_registered += 1

    # --- run_worker --------------------------------------------------
    #
    # Fire-and-forget fan-out. Workers report later via SUBAGENT_REPORT, and
    # ColonyRuntime.watch_batch_timeouts owns soft/hard timeout enforcement.

    _RUN_PARALLEL_DEFAULT_TIMEOUT = 600.0  # soft timeout (10 min)
    _RUN_PARALLEL_HARD_TIMEOUT_CAP = 3600.0  # absolute safety-net cap (1 hour)

    def _compute_hard_timeout(soft: float) -> float:
        """Default hard cutoff: max(4× soft, soft + 600), capped at 3600s."""
        return min(
            _RUN_PARALLEL_HARD_TIMEOUT_CAP,
            max(soft * 4.0, soft + 600.0),
        )

    def _get_unified_colony():
        """Read the unified ColonyRuntime (Phase 2 wiring) from session."""
        return getattr(session, "colony", None)

    async def run_worker(
        *,
        tasks: list[dict] | None = None,
        timeout: float | None = None,
        max_iterations: int | None = None,
        tool_call_lifetime_budget: int | None = None,
        resume_worker_ids: list[str] | None = None,
        guidance: str | None = None,
    ) -> str:
        """Spawn N parallel workers — OR resume stopped workers — and return immediately.

        Spawn mode (default): pass ``tasks``, a list of
        ``{"task": str, "data": dict | None}``. Workers run in the
        background; each emits a ``SUBAGENT_REPORT`` the queen sees as a
        ``[WORKER_REPORT]`` user turn. The queen stays unblocked.

        Resume mode: pass ``resume_worker_ids`` (a list of worker_ids of
        workers that stopped before reporting — e.g. timed-out or
        force-stopped). Each is reloaded from its saved conversation and
        continues from where it left off, then reports via
        ``report_to_parent``. Pass ``guidance`` to inject one steering
        message into every resumed worker before it continues. Pass
        ``max_iterations`` to extend the iteration ceiling (a worker that
        stopped near its limit needs headroom to finish). ``tasks`` and
        ``resume_worker_ids`` are mutually exclusive.

        ``timeout`` is a **soft** deadline (default 600s). When it
        expires, each still-active worker without an explicit report
        gets a SOFT TIMEOUT inject telling it to call ``report_to_parent``
        now. Workers ignoring the warning are force-stopped at a hard
        deadline derived from ``timeout`` (``max(timeout × 4,
        timeout + 600)``, capped at 3600s) — the derivation is not
        agent-tunable.
        """
        colony = _get_unified_colony()
        if colony is None:
            return json.dumps(
                {
                    "error": (
                        "No unified ColonyRuntime on this session. "
                        "Phase 2 wiring expects session.colony to be set "
                        "by SessionManager._start_unified_colony_runtime."
                    )
                }
            )

        # Spawn vs resume are mutually exclusive. Validate the chosen mode
        # up front so the queen gets a clear error instead of a confusing
        # downstream failure.
        _resume_mode = resume_worker_ids is not None
        if _resume_mode and tasks:
            return json.dumps({"error": "Pass either 'tasks' (spawn) or 'resume_worker_ids' (resume), not both."})
        if _resume_mode:
            if not isinstance(resume_worker_ids, list) or not resume_worker_ids:
                return json.dumps({"error": "resume_worker_ids must be a non-empty list of worker_id strings"})
        elif not isinstance(tasks, list) or not tasks:
            return json.dumps({"error": "tasks must be a non-empty list of {task, data?} dicts"})

        # Concurrency cap is enforced INSIDE the colony scheduler now,
        # not here. spawn_batch admits all N tasks; whatever exceeds
        # ``colony.max_concurrent_workers`` lands in the pending queue
        # and starts as running peers terminate. The queen sees the
        # split via ``running_now`` / ``queued`` in the immediate
        # return below, and via ``batch_remaining`` (which counts both
        # queued and running) on each [WORKER_REPORT].

        # Credential preflight — mirrors the one run_agent_with_input
        # performs. Without this, missing credentials (e.g. stale
        # GITHUB_TOKEN) fail once PER spawned worker, yielding N
        # duplicate error reports for a single fixable issue. Catch
        # once upfront, build a filtered tool list, and pass it to
        # every spawn via tools_override.
        legacy_for_preflight = _get_runtime()
        unavailable_tools_parallel: set[str] = set()
        if legacy_for_preflight is not None:
            try:
                unavailable_tools_parallel = await _preflight_credentials(legacy_for_preflight, tool_label="run_worker")
            except CredentialError as e:
                # Structured credential failure: publish the
                # CREDENTIALS_REQUIRED event so the frontend's modal
                # can fire, and return the same shape the single-path
                # tool returns on the same failure.
                error_payload = credential_errors_to_json(e)
                error_payload["agent_path"] = str(getattr(session, "worker_path", "") or "")
                bus = getattr(session, "event_bus", None)
                if bus is not None:
                    await bus.publish(
                        AgentEvent(
                            type=EventType.CREDENTIALS_REQUIRED,
                            stream_id="queen",
                            data=error_payload,
                        )
                    )
                return json.dumps(error_payload)

        # Always strip queen-lifecycle tools (run_worker,
        # switch_to_*) — without it the spawned worker could recurse or
        # flip the parent queen's phase. This applies whether or not
        # legacy preflight ran.
        from framework.server.routes_execution import _resolve_queen_only_tools

        queen_only = _resolve_queen_only_tools()

        # Strict bound: workers may only see tools the SPAWNING QUEEN
        # currently has in her phase. Without this, workers get the
        # entire colony pipeline's tool set (which can be a superset
        # of what the queen herself can call), and the queen would be
        # delegating capabilities she doesn't own. Read her current
        # available_tools off the queen loop — same path
        # ``fork_session_into_colony`` uses to snapshot the worker
        # template at colony-creation time. None means "queen ctx not
        # available, fall back to no scope filter" so legacy tests +
        # cold-start sessions still work.
        queen_tool_names: set[str] | None = None
        try:
            queen_executor = getattr(session, "queen_executor", None)
            node_registry = getattr(queen_executor, "node_registry", None)
            queen_loop = node_registry.get("queen") if isinstance(node_registry, dict) else None
            queen_ctx = getattr(queen_loop, "_last_ctx", None)
            if queen_ctx is not None:
                queen_tool_names = {getattr(t, "name", None) for t in (queen_ctx.available_tools or []) if getattr(t, "name", None)}
        except Exception:
            logger.debug(
                "run_worker: failed to read queen available_tools; falling back to full colony tool set",
                exc_info=True,
            )
            queen_tool_names = None

        colony_tools = list(getattr(colony, "_tools", []) or [])
        before = len(colony_tools)
        tools_override_parallel: list[Any] = [
            t
            for t in colony_tools
            if getattr(t, "name", None) not in queen_only
            and getattr(t, "name", None) not in unavailable_tools_parallel
            and (queen_tool_names is None or getattr(t, "name", None) in queen_tool_names)
        ]
        dropped = before - len(tools_override_parallel)
        if dropped:
            logger.info(
                "run_worker: stripped %d tool(s) from spawn_tools (queen-only / unavailable-credential / outside queen scope; queen scope size=%s)",
                dropped,
                len(queen_tool_names) if queen_tool_names is not None else "n/a",
            )

        # ── Resume mode ──────────────────────────────────────────────
        # Reload stopped/historical workers from their saved state and
        # continue them, instead of spawning fresh. Shares the credential
        # preflight + queen-scoped tool filtering above (so a resumed
        # worker runs with the queen's CURRENT tool scope), but skips the
        # spawn-only task normalization / tracker-registry gate — the
        # worker already coordinated through the tracker on its first run.
        if _resume_mode:
            import uuid as _uuid
            from datetime import UTC as _UTC, datetime as _dt

            resume_batch_id = _dt.now(_UTC).strftime("rsw_%Y%m%dT%H%M%SZ_") + _uuid.uuid4().hex[:8]
            ids = [str(w).strip() for w in resume_worker_ids]
            results: list[dict[str, Any]] = []
            resumed_ids: list[str] = []
            for idx, wid in enumerate(ids):
                if not wid:
                    results.append({"worker_id": wid, "status": "error", "error": "empty worker_id"})
                    continue
                try:
                    await colony.resume_worker(
                        wid,
                        tools_override=tools_override_parallel,
                        guidance=guidance,
                        max_iterations=max_iterations,
                        tool_call_lifetime_budget=tool_call_lifetime_budget,
                        batch_id=resume_batch_id,
                        batch_index=idx + 1,
                        batch_size=len(ids),
                    )
                except (ValueError, RuntimeError) as e:
                    results.append({"worker_id": wid, "status": "error", "error": str(e)})
                    continue
                except Exception as e:  # noqa: BLE001 — surface unexpected failures per-id
                    logger.warning("run_worker resume failed for %s: %s", wid, e, exc_info=True)
                    results.append({"worker_id": wid, "status": "error", "error": f"resume failed: {e}"})
                    continue
                resumed_ids.append(wid)
                w = colony._workers.get(wid) if hasattr(colony, "_workers") else None
                results.append(
                    {
                        "worker_id": wid,
                        "status": "resumed",
                        "initial_status": ("queued" if (w is not None and getattr(w, "is_queued", False)) else "running"),
                        "output_file": (getattr(w, "output_file", "") or "") if w is not None else "",
                    }
                )

            if resumed_ids:
                # Workers are live again — move the queen into the colony phase.
                if phase_state is not None:
                    try:
                        await phase_state.switch_to_colony()
                    except Exception as exc:
                        logger.warning("run_worker (resume): phase transition failed (non-fatal): %s", exc)
                _resume_soft = timeout if timeout is not None else _RUN_PARALLEL_DEFAULT_TIMEOUT
                _resume_hard = _compute_hard_timeout(_resume_soft)
                if _resume_hard <= _resume_soft:
                    _resume_hard = _resume_soft + 60.0
                try:
                    colony.watch_batch_timeouts(resumed_ids, soft_timeout=_resume_soft, hard_timeout=_resume_hard)
                except Exception as exc:
                    logger.warning("run_worker (resume): failed to schedule timeout watcher (non-fatal): %s", exc)

            return json.dumps(
                {
                    "status": "resumed",
                    "batch_id": resume_batch_id,
                    "resumed_count": len(resumed_ids),
                    "requested_count": len(ids),
                    "workers": results,
                    "message": (
                        f"Resumed {len(resumed_ids)} of {len(ids)} worker(s). Each resumed worker "
                        "continues from its saved conversation and emits a fresh [WORKER_REPORT] "
                        "when it terminates. Workers that could not be resumed are listed with an "
                        "'error' status (e.g. still active, no saved state, or unknown id)."
                    ),
                }
            )

        # Resolve the ColonyBinding for this run. The queen's own exec
        # context carries the binding once ``fork_session_into_colony``
        # has stamped it, so the preflight registry check below targets
        # the same tracker.db the queen wrote her DDL to. ``session``
        # and ``colony`` are checked as fallbacks for the few code paths
        # (mostly tests) that drive the queen without going through fork.
        from framework.host.colony_binding import ColonyBinding, current_binding
        from framework.host.tracker_db import ensure_tracker_db as _ensure_tracker_db

        _binding: ColonyBinding | None = current_binding()
        if _binding is None:
            _name = getattr(session, "colony_id", None) or getattr(colony, "colony_id", None)
            if _name:
                _binding = ColonyBinding.for_name(str(_name))
        # Make sure the DB exists. The fork flow already does this, but
        # tests that build the binding by hand may not.
        if _binding is not None:
            try:
                await asyncio.to_thread(_ensure_tracker_db, _binding.dir)
            except Exception as exc:
                logger.warning(
                    "run_worker: ensure_tracker_db failed: %s",
                    exc,
                )
        # Hard prerequisite: parallel workers must coordinate via the
        # tracker. Refuse to spawn unless at least one table is
        # registered for worker writes. Without it workers have no
        # shared primitive for claiming work and the queen has no way
        # to validate progress mid-batch — markdown files and prose
        # reports cannot replace it.
        if _binding is None:
            return json.dumps(
                {
                    "error": (
                        "run_worker: no colony binding in the "
                        "execution context. Workers cannot be coordinated "
                        "without one — this queen has not created a colony."
                    ),
                }
            )
        try:
            import sqlite3 as _sqlite3

            _con = _sqlite3.connect(str(_binding.tracker_db))
            try:
                _row = _con.execute("SELECT COUNT(*) FROM _tracker_registry").fetchone()
                _reg_count = int(_row[0]) if _row else 0
            finally:
                _con.close()
        except Exception as exc:
            # Fail closed: if we can't read the registry, treat it as
            # empty so the queen gets the same actionable error rather
            # than discovering the problem one-per-worker at upsert time.
            logger.warning(
                "run_worker: tracker registry check failed; treating as unregistered: %s",
                exc,
            )
            _reg_count = 0
        if _reg_count == 0:
            return json.dumps(
                {
                    "error": (
                        "No tables registered for worker writes. Before "
                        "calling run_worker: (1) model the work as "
                        "a row-shape table with "
                        "tracker_sql('CREATE TABLE <name> (...)'), (2) "
                        "register it with tracker_register_writable("
                        "table='<name>', write_columns=[...], "
                        "key_columns=[...]). Workers need a shared tracker "
                        "to coordinate — markdown files and prose reports "
                        "cannot replace it."
                    ),
                }
            )

        # Normalise: each entry must have a non-empty "task" string.
        normalised: list[dict] = []
        for i, spec in enumerate(tasks):
            if not isinstance(spec, dict):
                return json.dumps({"error": f"tasks[{i}] is not a dict: {type(spec).__name__}"})
            task_text = str(spec.get("task", "")).strip()
            if not task_text:
                return json.dumps({"error": f"tasks[{i}].task is empty"})
            spec_data = spec.get("data") if isinstance(spec.get("data"), dict) else {}
            spec_data = {**spec_data, "binding": _binding.to_dict()}
            entry: dict[str, Any] = {
                "task": task_text,
                "data": spec_data,
            }
            if spec.get("profile_name"):
                entry["profile_name"] = str(spec["profile_name"])
            if isinstance(spec.get("goal"), str) and spec["goal"].strip():
                entry["goal"] = spec["goal"].strip()
            # Tool-tiering preload: exact names to promote into the worker's
            # eager set at spawn (validated against the pool downstream).
            _preload = spec.get("preload_tools")
            if isinstance(_preload, list):
                _preload_clean = [str(n).strip() for n in _preload if isinstance(n, str) and str(n).strip()]
                if _preload_clean:
                    entry["preload_tools"] = _preload_clean
            # Per-task budget / timeout overrides were removed from the
            # public schema: heterogeneous batches are almost always a
            # smell, and agents that genuinely need different limits per
            # worker should run two batches. Any keys still present on
            # ``spec`` from legacy callers are silently dropped here.
            normalised.append(entry)

        logger.info(
            "run_worker: attached binding to %d spawn(s) (colony=%s)",
            len(normalised),
            _binding.name,
        )

        # Preserve the task text in spec["data"]. Once spec["data"] is
        # non-empty, spawn()'s ``input_data or {"task": task}`` fallback no
        # longer fires, so the task description would otherwise vanish from
        # the worker's first user message.
        for spec in normalised:
            spec["data"] = dict(spec.get("data") or {})
            spec["data"].setdefault("task", spec["task"])

        # Batch-level budget overrides: only include fields the queen
        # explicitly passed (None = leave the framework default alone).
        batch_loop_overrides: dict[str, Any] = {}
        if isinstance(max_iterations, int):
            batch_loop_overrides["max_iterations"] = max_iterations
        if isinstance(tool_call_lifetime_budget, int):
            batch_loop_overrides["tool_call_lifetime_budget"] = tool_call_lifetime_budget

        # Mint the batch_id here so we can return it in the immediate
        # response — the queen uses it to correlate the [WORKER_REPORT]s
        # she'll receive against this specific spawn call.
        import uuid as _uuid
        from datetime import UTC as _UTC, datetime as _dt

        batch_id = _dt.now(_UTC).strftime("rpw_%Y%m%dT%H%M%SZ_") + _uuid.uuid4().hex[:8]
        try:
            worker_ids = await colony.spawn_batch(
                normalised,
                tools_override=tools_override_parallel,
                loop_config_overrides=batch_loop_overrides or None,
                batch_id=batch_id,
            )
        except Exception as e:
            return json.dumps({"error": f"spawn_batch failed: {e}"})

        # Phase transition — workers are now live, queen is in "colony"
        # phase. Colony phase covers both live and finished states, so no
        # follow-up transition is needed when workers report.
        # switch_to_colony persists phase to meta.json itself; no external
        # _update_meta_json call needed.
        if phase_state is not None:
            try:
                await phase_state.switch_to_colony()
            except Exception as exc:
                logger.warning(
                    "run_worker: phase transition to 'colony' failed (non-fatal): %s",
                    exc,
                )

        # Soft + hard timeout watcher runs in the background. At soft,
        # it injects a "wrap up" message to every still-active worker
        # without an explicit report; at hard, it force-stops the
        # stragglers. ``hard`` is always derived from ``soft`` — the
        # agent no longer tunes it directly (the derivation handles
        # ~99% of cases and one fewer knob trims the tool surface).
        batch_soft = timeout if timeout is not None else _RUN_PARALLEL_DEFAULT_TIMEOUT
        batch_hard = _compute_hard_timeout(batch_soft)
        if batch_hard <= batch_soft:
            batch_hard = batch_soft + 60.0  # enforce at least a 60s grace
        try:
            colony.watch_batch_timeouts(
                worker_ids,
                soft_timeout=batch_soft,
                hard_timeout=batch_hard,
            )
        except Exception as exc:
            logger.warning(
                "run_worker: failed to schedule timeout watcher (non-fatal): %s",
                exc,
            )
        soft_timeout = batch_soft
        hard_timeout_effective = batch_hard

        # Per-worker breadcrumbs the queen needs at spawn time to
        # correlate later reports: worker_id, the task slice each was
        # given (preview), the initial state (running vs queued), and
        # the on-disk transcript path she can read if (and only if) the
        # user asks for live progress on a specific worker.
        workers_breadcrumbs: list[dict[str, Any]] = []
        running_now = 0
        queued = 0
        for i, wid in enumerate(worker_ids):
            spec = normalised[i] if i < len(normalised) else {}
            task_text = str(spec.get("task", ""))
            preview = task_text.strip().replace("\n", " ")
            if len(preview) > 200:
                preview = preview[:200] + "…"
            output_file = ""
            initial_status = "running"
            try:
                w = colony._workers.get(wid) if hasattr(colony, "_workers") else None
                if w is not None:
                    output_file = getattr(w, "output_file", "") or ""
                    if getattr(w, "is_queued", False):
                        initial_status = "queued"
                        queued += 1
                    else:
                        running_now += 1
            except Exception:
                running_now += 1
            workers_breadcrumbs.append(
                {
                    "worker_id": wid,
                    "task_index": i + 1,
                    "task_preview": preview,
                    "output_file": output_file,
                    "initial_status": initial_status,
                }
            )

        # Read the colony's effective concurrency cap so the message
        # text can reflect what the queen is actually working with.
        try:
            _max_concurrent = int(colony._config.max_concurrent_workers)
        except Exception:
            _max_concurrent = 0

        return json.dumps(
            {
                "status": "started",
                "batch_id": batch_id,
                "worker_count": len(worker_ids),
                "worker_ids": worker_ids,
                "workers": workers_breadcrumbs,
                "running_now": running_now,
                "queued": queued,
                "max_concurrent_workers": _max_concurrent,
                "soft_timeout_seconds": soft_timeout,
                "hard_timeout_seconds": hard_timeout_effective,
                "message": (
                    f"Dispatched {len(worker_ids)} workers — {running_now} "
                    f"running now, {queued} queued (colony cap: "
                    f"{_max_concurrent}). Each emits one structured "
                    "[WORKER_REPORT] user turn when it terminates, "
                    "including queued workers; reports carry "
                    "<batch_remaining>N</batch_remaining> covering BOTH "
                    "still-running AND still-queued peers in this batch. "
                    "Validate the tracker only AFTER you see "
                    "<batch_remaining>0</batch_remaining> in a report — "
                    "until then more results are still coming. Three rules:\n"
                    "  1. Don't poll: do NOT call get_worker_status just "
                    "to fill silence. Wait for [WORKER_REPORT].\n"
                    "  2. Don't fabricate: never predict, summarise, or "
                    "guess worker results before the report arrives. If "
                    "the user asks before reports land, say workers are "
                    "still running — give status, not a guess.\n"
                    "  3. Don't peek: only inspect a worker's output_file "
                    "when the user explicitly asks for live progress on "
                    "a specific worker; you can check the tracker "
                    "for overall progress"
                ),
            }
        )

    _run_parallel_tool = Tool(
        name="run_worker",
        description=(
            "Lower-level fan-out — PREFER run_playbook for row-shaped work. "
            "For N units of the same job over a tracker table, run_playbook "
            "converges the table deterministically (one worker per undone unit "
            "— usually a CHUNK of 5-10 rows — with retry / dead-letter / "
            "resume) instead of making you re-coordinate each report. Reach "
            "for run_worker only for one-off heterogeneous tasks that don't "
            "fit a table, or when each report genuinely needs your judgment.\n\n"
            "BATCH SIMILAR UNITS — 5-10 PER WORKER. Every worker pays a fixed "
            "orientation tax before its first useful action: fresh context, "
            "system prompt, skill reads — roughly 2-3k tokens. One-small-unit-"
            "per-worker multiplies that tax by N for nothing (measured live: "
            "a 68-worker one-lead-each batch spent ~200-300k tokens on "
            "orientation alone). Give each worker a slice of 5-10 similar "
            "units and a timeout that covers the whole slice; reserve "
            "one-unit workers for units that are individually large. Tell "
            "the worker to process its slice as consecutive tool calls, "
            "recording each unit as it goes — it does not need a turn per "
            "unit, so the default turn budget fits a slice.\n\n"
            "Fan out a batch of tasks to parallel workers and RETURN "
            "IMMEDIATELY. Workers run in the background; each one reports "
            "back to you as a [WORKER_REPORT] user turn when it finishes, "
            "so you stay unblocked and can chat with the user, kick off "
            "more work, or do anything else in the meantime.\n\n"
            "FACTOR SHARED CONTEXT INTO A SKILL FIRST. Each worker is a "
            "fresh process with no memory of your conversation, but that "
            "does NOT mean you should duplicate the same protocol prose "
            "across N task strings. If 90% of every task string is the "
            "same — schema, output format, quality bar, tools to use — "
            "stop and call ``write_skill`` once with that common ground. "
            "Workers spawned afterwards see the new skill in their "
            "``<available_skills>`` catalog and activate it on demand. "
            "Reference the skill BY NAME in the task string (e.g. 'Follow "
            "the <skill-name> protocol to extract rows X, Y, Z') so each "
            "worker reads it once and the task strings only carry the "
            "per-worker DIFFERENCES (which 5 companies, which row IDs, "
            "which date range). Don't spend N× tokens saying the "
            "same thing.\n\n"
            "Per-task strings still need to be self-contained for the "
            "*differences*: include row keys, IDs, URLs, anything unique "
            "to that worker's slice. Workers cannot ask the user follow-up "
            "questions and cannot see your chat history.\n\n"
            "NON-OVERLAPPING SLICES. Workers run concurrently, cannot "
            "coordinate, and cannot see each other. Two tasks that touch "
            "the same tracker rows, files, or records will double-write "
            "or collide. Partition the work cleanly — each row/file/record "
            "should be owned by exactly one worker.\n\n"
            "Browser tasks: each worker gets its OWN Chrome tab group, "
            "isolated from the queen's tabs and from every other worker, "
            "but within the SAME Chrome profile — so workers share "
            "cookies and logged-in sessions with the queen (a site the "
            "queen is logged into is also authenticated for workers). "
            "Each browser worker should start "
            " with `hive-browser open`/`hive-browser navigate`; auth carries over "
            "from the shared profile. Live per-worker tab activity is "
            "visible to the queen via get_worker_status "
            "(focus='full' → 'worker_browsers').\n\n"
            "Each worker runs in isolation with its own AgentLoop and "
            "reports back via the report_to_parent tool. The tool "
            "returns a JSON object with status='started' and the list "
            "of worker_ids you just spawned. Each worker's completion "
            "arrives later as a [WORKER_REPORT] message containing "
            "worker_id, status (success|partial|failed|timeout|stopped), "
            "summary, data, error, duration. Read those messages as "
            "they arrive and respond to the user naturally.\n\n"
            "TIMEOUT — 'timeout' is a SOFT deadline (default 600s). "
            "When it expires, every still-active worker that hasn't "
            "reported gets a [SOFT TIMEOUT] message telling it to "
            "call report_to_parent now. The hard cutoff (when "
            "stragglers are force-stopped) is derived from 'timeout' "
            "automatically and is not agent-tunable. Explicit reports "
            "filed during the warning window ARE preserved.\n\n"
            "HETEROGENEOUS BATCHES — if some workers need different "
            "iteration / timeout budgets than others, run two batches "
            "rather than mixing. The interface intentionally exposes "
            "only batch-level knobs."
        ),
        parameters={
            "type": "object",
            "properties": {
                "tasks": {
                    "type": "array",
                    "description": (
                        "List of task specs to fan out. Each spec is "
                        '{"task": "<description>", "data": {<optional structured input>}}. '
                        "The 'task' string becomes the worker's initial "
                        "user message — keep it tight and per-worker UNIQUE "
                        "(don't duplicate the shared protocol). "
                        "'data' is merged into the worker's "
                        "AgentContext.input_data so structured fields are "
                        "available to the worker's first turn."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "task": {
                                "type": "string",
                                "description": "Task description for the worker.",
                            },
                            "data": {
                                "type": "object",
                                "description": "Optional structured input fields.",
                            },
                            "goal": {
                                "type": "string",
                                "description": (
                                    "One sentence, in plain end-user language, "
                                    "describing what this worker is doing (e.g. "
                                    "'Checking 20 Instagram profiles to see who "
                                    "accepts DMs'). Shown in the UI as the "
                                    "worker's title — ALWAYS provide it; a "
                                    "non-technical user should understand it. "
                                    "Not shown to the worker."
                                ),
                            },
                            "preload_tools": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Exact tool names to pre-load into this "
                                    "worker's eager toolset at spawn (skips its "
                                    "search_tools round-trip). Use when you KNOW "
                                    "the task needs tools that are searchable "
                                    "for workers (e.g. sender or hubspot tools). "
                                    "Unknown names are ignored."
                                ),
                            },
                        },
                        "required": ["task"],
                    },
                    "minItems": 1,
                },
                "max_iterations": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1000,
                    "description": (
                        "Cap on each worker's AgentLoop iterations of useful "
                        "work. After this is exhausted the framework grants "
                        "an additional grace iteration (configured separately) "
                        "where dispatch is restricted to report_to_parent / "
                        "tracker_upsert / task_update so the worker can wrap "
                        "up. Worker default: 3 (work) + 1 (grace) = 4 total."
                    ),
                },
                "timeout": {
                    "type": "number",
                    "description": (
                        "SOFT deadline in seconds. Workers still running "
                        "at this point are messaged to call report_to_parent. "
                        "Default 600 (10 minutes)."
                    ),
                },
                "tool_call_lifetime_budget": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 2000,
                    "description": (
                        "Cap on each worker's CUMULATIVE tool calls across ALL its "
                        "turns (distinct from max_iterations, which counts turns, and "
                        "from the per-turn pacing budget). When a worker reaches this "
                        "total it is forced into the grace wind-down — a stop reminder "
                        "is injected and dispatch is restricted to report_to_parent / "
                        "tracker_upsert / task_update so it reports back instead of "
                        "running unbounded. Worker default: 150. Lower it (e.g. 20) to "
                        "keep tool-heavy workers on a tight leash; on resume it also "
                        "RAISES the ceiling for a worker that already exhausted its "
                        "budget (the count persists across resumes). OMIT this to let "
                        "the colony's adaptive budget manage the fan-out: successful "
                        "workers' consumption sets the colony norm and outlier workers "
                        "are wound down early. Passing an explicit value PINS those "
                        "workers to it — they are neither clamped by nor counted "
                        "toward the adaptive norm."
                    ),
                },
                "resume_worker_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "RESUME mode (mutually exclusive with 'tasks'). worker_ids "
                        "of workers that stopped before reporting (e.g. timed-out or "
                        "force-stopped) — you have these from the original run_worker "
                        "return and the stopped/timeout [WORKER_REPORT]s. Each is "
                        "reloaded from its saved conversation and continues from where "
                        "it left off, then reports via report_to_parent. Pass "
                        "'max_iterations' to give a worker that stopped near its limit "
                        "room to finish, and 'guidance' to steer it before it resumes."
                    ),
                    "minItems": 1,
                },
                "guidance": {
                    "type": "string",
                    "description": (
                        "RESUME mode only: a single steering instruction injected as a "
                        "user turn into every resumed worker before it continues (e.g. "
                        "'you got stuck on the login step — try the API instead'). "
                        "Ignored when spawning fresh workers via 'tasks'."
                    ),
                },
            },
        },
    )
    registry.register(
        "run_worker",
        _run_parallel_tool,
        lambda inputs: run_worker(**inputs),
    )
    tools_registered += 1

    # --- write_skill ----------------------------------------------------------
    #
    # Author colony-scoped skills so later workers can share protocol without
    # repeating it in every task string.

    async def write_skill_tool(
        *,
        skill_name: str | None = None,
        skill_description: str | None = None,
        skill_body: str | None = None,
        skill_files: list[dict] | None = None,
        source_path: str | None = None,
    ) -> str:
        """Write or replace a colony-scoped skill.

        Two modes:

        - **Inline** (default): pass ``skill_name`` + ``skill_description``
          + ``skill_body``, with optional ``skill_files``. The skill is
          materialized from those arguments.
        - **Copy from source**: pass ``source_path`` pointing at an
          existing skill's root directory (the one that contains
          ``SKILL.md``). The tool reads ``SKILL.md`` + every other file
          in that directory and writes them all into the colony scope.
          ``skill_name`` may be supplied to rename the skill on copy;
          the other inline params are rejected in this mode to keep
          the contract unambiguous (use inline mode if you want to
          edit content).

        Either way the skill lands at
        ``~/.hive/colonies/{colony_id}/skills/{skill_name}/`` and is
        immediately visible in the ``<available_skills>`` catalog of
        subsequently-spawned workers, who can activate it on demand.
        Replaces an existing skill of the same name in place — the
        queen owns her colony-scoped skill namespace.
        """
        if session is None:
            return json.dumps({"error": "No session bound to this tool registry."})

        # Resolve colony_id from session (preferred) or live runtime.
        colony_id_resolved = getattr(session, "colony_id", None) or getattr(_get_unified_colony() or _get_runtime(), "colony_id", None)
        if not colony_id_resolved:
            return json.dumps(
                {
                    "error": (
                        "write_skill: no colony bound to this session. "
                        "This tool only works once the colony has been "
                        "forked (via the Create Colony popup) and you're "
                        "operating inside it."
                    )
                }
            )

        from framework.config import COLONIES_DIR
        from framework.skills.parser import parse_skill_md
        from framework.skills.skill_writer import build_draft, write_skill

        # ---- Mode selection: source_path vs. inline -----------------
        # In copy mode we read the SKILL.md + auxiliary files off disk
        # and short-circuit the inline-required fields. Aux files are
        # walked recursively; binaries (anything that can't be decoded
        # as UTF-8) trigger an explicit error rather than silent loss.
        if source_path is not None:
            if any(v is not None for v in (skill_description, skill_body, skill_files)):
                return json.dumps(
                    {
                        "error": (
                            "write_skill: source_path mode does not accept "
                            "skill_description / skill_body / skill_files. "
                            "Pass only source_path (and optionally skill_name "
                            "to rename). Use inline mode if you need to edit "
                            "content."
                        )
                    }
                )

            from pathlib import Path as _Path

            src = _Path(source_path).expanduser()
            if not src.exists():
                return json.dumps({"error": f"source_path '{source_path}' does not exist"})
            # Accept either the skill root dir or its SKILL.md directly.
            if src.is_file() and src.name == "SKILL.md":
                src = src.parent
            if not src.is_dir():
                return json.dumps({"error": (f"source_path '{source_path}' must be a skill root directory (containing SKILL.md)")})
            skill_md = src / "SKILL.md"
            if not skill_md.is_file():
                return json.dumps({"error": f"source_path '{source_path}' has no SKILL.md"})

            parsed = parse_skill_md(skill_md, source_scope="user")
            if parsed is None:
                return json.dumps(
                    {
                        "error": (
                            f"failed to parse SKILL.md at '{skill_md}' — check the frontmatter is valid YAML and has a non-empty 'description' field"
                        )
                    }
                )

            resolved_name = skill_name or parsed.name
            resolved_description = parsed.description
            resolved_body = parsed.body

            # Walk auxiliary files. Skip SKILL.md (handled via body) and
            # anything outside the source dir. Hidden files (e.g. .DS_Store)
            # are skipped to avoid copying OS cruft.
            sourced_files: list[dict] = []
            binary_files: list[str] = []
            try:
                src_resolved = src.resolve()
                skill_md_resolved = skill_md.resolve()
                for f in sorted(src.rglob("*")):
                    if not f.is_file():
                        continue
                    if f.resolve() == skill_md_resolved:
                        continue
                    # Refuse symlinks that escape the source dir.
                    try:
                        f.resolve().relative_to(src_resolved)
                    except ValueError:
                        continue
                    rel = f.relative_to(src).as_posix()
                    if any(part.startswith(".") for part in _Path(rel).parts):
                        continue
                    try:
                        content = f.read_text(encoding="utf-8")
                    except UnicodeDecodeError:
                        binary_files.append(rel)
                        continue
                    except OSError as e:
                        return json.dumps({"error": f"failed to read '{rel}' under source_path: {e}"})
                    sourced_files.append({"path": rel, "content": content})
            except OSError as e:
                return json.dumps({"error": f"failed to walk source_path: {e}"})

            if binary_files:
                return json.dumps(
                    {
                        "error": (
                            "write_skill: source skill contains non-UTF8 "
                            "files which the skill writer can't carry: "
                            f"{binary_files}. Remove or replace them in the "
                            "source, or copy by hand."
                        )
                    }
                )

            skill_name = resolved_name
            skill_description = resolved_description
            skill_body = resolved_body
            skill_files = sourced_files

        else:
            if not skill_name or not skill_description or not skill_body:
                return json.dumps(
                    {
                        "error": (
                            "write_skill: inline mode requires skill_name, "
                            "skill_description, and skill_body. Or pass "
                            "source_path to copy an existing skill folder."
                        )
                    }
                )

        colony_dir = COLONIES_DIR / colony_id_resolved
        try:
            colony_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return json.dumps({"error": f"failed to create colony dir: {e}"})

        draft, draft_err = build_draft(
            skill_name=skill_name,
            skill_description=skill_description,
            skill_body=skill_body,
            skill_files=skill_files,
        )
        if draft_err is not None or draft is None:
            return json.dumps(
                {
                    "error": draft_err or "invalid skill draft",
                    "hint": (
                        "Provide skill_name (lowercase [a-z0-9-], ≤64 chars), "
                        "skill_description (single line, 1–1024 chars), and "
                        "skill_body (the operational procedure: schema columns, "
                        "tool conventions, output format, quality bar, gotchas). "
                        "Use skill_files for optional scripts/references. Or "
                        "pass source_path to copy an existing skill folder."
                    ),
                }
            )

        installed, write_err, replaced = write_skill(
            draft,
            target_root=colony_dir / "skills",
            replace_existing=True,
        )
        if write_err is not None or installed is None:
            return json.dumps({"error": write_err or "failed to write skill folder"})

        # Force a synchronous catalog reload so the next ``run_worker``
        # in the same turn sees the new skill. The hot-reload watcher would
        # eventually pick it up (1s debounce), but workers spawned in the same
        # tick as ``write_skill`` race the watcher and end up with a stale
        # ``<available_skills>`` snapshot. Reloading here also refreshes
        # ``skill_dirs`` (the worker's Tier-3 read allowlist) so the new
        # SKILL.md is readable as well as discoverable.
        runtime = _get_runtime() or _get_unified_colony()
        if runtime is not None and hasattr(runtime, "reload_skills"):
            try:
                await runtime.reload_skills()
            except Exception:
                logger.exception(
                    "write_skill: catalog reload after write failed; workers spawned this turn may not see '%s' until the hot-reload watcher fires",
                    draft.name,
                )

        return json.dumps(
            {
                "success": True,
                "colony_id": colony_id_resolved,
                "skill_name": draft.name,
                "skill_path": str(installed),
                "replaced": replaced,
                "source_path": source_path,
                "files_copied": len(skill_files or []),
                "message": (
                    f"Skill '{draft.name}' is ready. Workers spawned "
                    f"after this call see it in their <available_skills> "
                    f"catalog and can activate it on demand — reference "
                    f"it BY NAME in the task string (e.g. 'follow the "
                    f"{draft.name} protocol') instead of repeating the "
                    f"protocol prose."
                ),
            }
        )

    _write_skill_tool = Tool(
        name="write_skill",
        description=(
            "Write or replace a colony-scoped skill. Use this BEFORE "
            "fanning out parallel workers when the per-task protocol is "
            "the same across all workers (schema, output format, tool "
            "conventions, quality bar). Writing the protocol ONCE into a "
            "skill — then pointing each worker at it BY NAME in the task "
            "string — is dramatically cheaper than duplicating the same "
            "prose across N task strings, and keeps the protocol "
            "consistent. Workers see the skill in their "
            "<available_skills> catalog and activate it on demand.\n\n"
            "TWO MODES:\n"
            "  - Inline: pass skill_name + skill_description + skill_body "
            "(and optional skill_files). Authors a fresh skill from "
            "arguments.\n"
            "  - Copy: pass source_path pointing at an existing skill "
            "root directory (the one containing SKILL.md). The tool "
            "reads SKILL.md plus every other file in that directory and "
            "writes them into the colony scope verbatim. Optionally pass "
            "skill_name to rename on copy. The other inline params are "
            "REJECTED in this mode — use inline mode if you need to "
            "edit content.\n\n"
            "Skill is colony-scoped: only THIS colony's workers see it. "
            "Replacing an existing skill of the same name is fine — "
            "your latest content wins. Workers spawned AFTER this call "
            "pick it up; existing workers do not.\n\n"
            "Skill body should read like a self-contained operating "
            "procedure: what the worker is doing, the exact tools/schema "
            "to use, the output format, what 'done' looks like. Skip "
            "the per-worker specifics — those go in the task string."
        ),
        parameters={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        "Lowercase, hyphen-separated, ≤64 chars (e.g. "
                        "'competitor-research-protocol'). Required in "
                        "inline mode; optional in source_path mode "
                        "(renames the skill on copy — defaults to the "
                        "source's frontmatter name)."
                    ),
                },
                "skill_description": {
                    "type": "string",
                    "description": (
                        "One-line summary of what this skill teaches a "
                        "worker. Surfaced in the worker's skill catalog. "
                        "Required in inline mode; rejected in "
                        "source_path mode (description comes from the "
                        "source SKILL.md frontmatter)."
                    ),
                },
                "skill_body": {
                    "type": "string",
                    "description": (
                        "Markdown body of SKILL.md — the operational "
                        "procedure the worker needs to run unattended. "
                        "Required in inline mode; rejected in "
                        "source_path mode."
                    ),
                },
                "skill_files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                    },
                    "description": (
                        "Optional supporting files (scripts, JSON refs, "
                        "etc.). Each entry is {path, content} where "
                        "path is relative to the skill root. Inline "
                        "mode only; rejected in source_path mode (the "
                        "tool walks the source dir and copies aux files "
                        "automatically)."
                    ),
                },
                "source_path": {
                    "type": "string",
                    "description": (
                        "Absolute or '~'-prefixed path to an existing "
                        "skill's root directory (the one that contains "
                        "SKILL.md). When set, the tool copies the entire "
                        "skill folder — SKILL.md + every other UTF-8 "
                        "file — into the colony scope. Use this to lift "
                        "a framework default skill, user-scoped skill, "
                        "or another colony's skill into THIS colony so "
                        "the queen can pilot/customize it locally."
                    ),
                },
            },
        },
    )
    registry.register(
        "write_skill",
        _write_skill_tool,
        lambda inputs: write_skill_tool(**inputs),
    )
    tools_registered += 1

    # --- update_worker_profile ---------------------------------------------------

    async def update_worker_profile(
        *,
        colony_id: str,
        profile_name: str,
        integrations: dict[str, str] | None = None,
        task: str | None = None,
        skill_name: str | None = None,
        concurrency_hint: int | None = None,
        prompt_override: str | None = None,
        tool_filter: list[str] | None = None,
        browser_profile: str | None = None,
    ) -> str:
        """Insert or update a single worker profile on an existing colony.

        Use this to adjust an account binding ("switch the slack-work
        profile from alias 'work' to alias 'work-2'") or to add a new
        profile after the colony was already created. Existing siblings
        are preserved. Pass only the fields you want to change; ``None``
        means "don't touch", and an empty dict/list means "clear".

        ``browser_profile`` binds this profile's browser tools to a specific
        Chrome profile, named by the label that profile's Hive extension
        advertises (see ``list_browser_profiles`` for the connected labels).
        Empty string clears it back to the default browser. Workers on this
        profile then drive that Chrome window's tabs — letting one colony run
        several Chrome profiles / logged-in accounts at once.
        """
        from framework.host.worker_profiles import (
            WorkerProfile,
            get_worker_profile,
            upsert_worker_profile,
            validate_profile_name,
        )

        cn = (colony_id or "").strip()
        if not _COLONY_NAME_RE.match(cn):
            return json.dumps({"error": "colony_id must be lowercase alphanumeric with underscores."})
        err = validate_profile_name(profile_name)
        if err is not None:
            return json.dumps({"error": err})

        existing = get_worker_profile(cn, profile_name)
        merged = WorkerProfile(
            name=profile_name,
            task=existing.task if existing else "",
            skill_name=existing.skill_name if existing else "",
            integrations=dict(existing.integrations) if existing else {},
            concurrency_hint=existing.concurrency_hint if existing else None,
            prompt_override=existing.prompt_override if existing else None,
            tool_filter=list(existing.tool_filter) if (existing and existing.tool_filter) else None,
            browser_profile=existing.browser_profile if existing else "",
        )
        if integrations is not None:
            merged.integrations = {str(k): str(v) for k, v in integrations.items() if str(k) and str(v)}
        if task is not None:
            merged.task = task
        if skill_name is not None:
            merged.skill_name = skill_name
        if concurrency_hint is not None:
            merged.concurrency_hint = concurrency_hint if isinstance(concurrency_hint, int) and concurrency_hint > 0 else None
        if prompt_override is not None:
            merged.prompt_override = prompt_override or None
        if tool_filter is not None:
            merged.tool_filter = list(tool_filter) if tool_filter else None
        if browser_profile is not None:
            merged.browser_profile = browser_profile.strip()

        try:
            saved = upsert_worker_profile(cn, merged)
        except (FileNotFoundError, ValueError) as exc:
            return json.dumps({"error": str(exc)})

        return json.dumps(
            {
                "ok": True,
                "colony_id": cn,
                "profile_name": profile_name,
                "worker_profiles": [p.to_dict() for p in saved],
            }
        )

    _update_worker_profile_tool = Tool(
        name="update_worker_profile",
        description=(
            "Insert or update one worker profile on an existing colony. "
            "Use this to swap a profile's account alias (e.g. 'switch "
            "slack-work to use alias work-2'), bind it to a specific Chrome "
            "profile via browser_profile (a connected label from "
            "list_browser_profiles), or add a profile after the colony was "
            "forked. Existing siblings are preserved. Pass only the fields you "
            "want to change."
        ),
        parameters={
            "type": "object",
            "properties": {
                "colony_id": {"type": "string"},
                "profile_name": {"type": "string"},
                "integrations": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                },
                "task": {"type": "string"},
                "skill_name": {"type": "string"},
                "concurrency_hint": {"type": "integer", "minimum": 1},
                "prompt_override": {"type": "string"},
                "tool_filter": {"type": "array", "items": {"type": "string"}},
                "browser_profile": {
                    "type": "string",
                    "description": ("Chrome profile label this profile's browser tools target (from list_browser_profiles). Empty clears it."),
                },
            },
            "required": ["colony_id", "profile_name"],
        },
    )
    registry.register(
        "update_worker_profile",
        _update_worker_profile_tool,
        lambda inputs: update_worker_profile(**inputs),
    )
    tools_registered += 1

    # --- list_browser_profiles ---------------------------------------------------

    async def list_browser_profiles() -> str:
        """List the Chrome profiles whose Hive extension is connected.

        Each entry's ``label`` is exactly what you pass as ``browser_profile``
        to ``update_worker_profile`` to bind a worker profile to that Chrome
        window. Labels are set by the user in each profile's extension side
        panel (auto-generated as a 3-word id until renamed). Discover real
        labels here before binding — a label that isn't connected makes the
        worker's browser tools fail fast rather than silently using another
        account.
        """
        import os

        # The bridge serves /profiles on its status port (WS port + 1); it also
        # binds the legacy 9230 during the migration window. Try both.
        bridge_port = int(os.environ.get("HIVE_BRIDGE_PORT", "14829"))
        for status_port in (bridge_port + 1, 9230):
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", status_port), timeout=0.5)
                writer.write(b"GET /profiles HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
                await writer.drain()
                raw = await asyncio.wait_for(reader.read(65536), timeout=0.5)
                writer.close()
            except Exception:
                continue
            if b"\r\n\r\n" not in raw:
                continue
            try:
                data = json.loads(raw.split(b"\r\n\r\n", 1)[1])
            except Exception:
                continue
            profiles = [
                {
                    "label": p.get("label"),
                    "is_default": bool(p.get("is_default")),
                    "starred": bool(p.get("starred")),
                    "version": p.get("version"),
                    "protocol_version": p.get("protocol_version"),
                }
                for p in (data.get("profiles") or [])
            ]
            out: dict = {"ok": True, "profiles": profiles}
            if not profiles:
                out["hint"] = (
                    "No Chrome profiles are connected. In each Chrome profile, install/enable the "
                    "Hive Browser Bridge extension and set its label in the side panel, then retry."
                )
            return json.dumps(out)
        return json.dumps(
            {
                "ok": False,
                "error": "browser bridge not reachable",
                "hint": "Is the Hive app running? The browser bridge serves /profiles on 127.0.0.1.",
                "profiles": [],
            }
        )

    _list_browser_profiles_tool = Tool(
        name="list_browser_profiles",
        description=(
            "List the Chrome profiles whose Hive extension is currently connected, each with the "
            "label to pass as browser_profile in update_worker_profile. Call this before binding "
            "workers to browser profiles so you bind to real, connected labels."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "list_browser_profiles",
        _list_browser_profiles_tool,
        lambda inputs: list_browser_profiles(**inputs),
    )
    tools_registered += 1

    # NOTE: session splitting is no longer a standalone tool. It is now the
    # ``new_session`` arg on ``task_create`` (wired in queen_orchestrator
    # via ``fork_queen_session_for_split``) — the queen forks a fresh
    # session only when laying out a plan for big, unrelated work, and the
    # new plan is seeded straight into that session.

    # NOTE: removed dead phase-transition tool stubs that were never registered
    # for the queen — ``switch_to_reviewing`` and ``stop_worker_and_review`` (the
    # latter broken: it called ``phase_state.switch_to_building``, removed with
    # the planning/building pipeline) — plus a duplicate ``stop_worker``
    # (``stop_worker_to_staging``) that registered under the same name and
    # silently OVERWROTE the colony ``stop_worker`` above, and their shared
    # helper ``_stop_result_allows_phase_transition``. Live phase transitions
    # remain on QueenPhaseState; git history preserves the wrappers if revived.

    # --- get_worker_status -----------------------------------------------------

    def _get_event_bus():
        """Get the session's event bus for querying history."""
        return getattr(session, "event_bus", None)

    # Tiered cooldowns: summary is free, detail has short cooldown, full keeps 30s
    _COOLDOWN_FULL = 30.0
    _COOLDOWN_DETAIL = 10.0
    _status_last_called: dict[str, float] = {}  # tier -> monotonic time

    def _format_elapsed(seconds: float) -> str:
        """Format seconds as human-readable duration."""
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, rem = divmod(s, 60)
        if m < 60:
            return f"{m}m {rem}s"
        h, m = divmod(m, 60)
        return f"{h}h {m}m"

    def _format_time_ago(ts) -> str:
        """Format a datetime as relative time ago."""

        now = datetime.now(UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        delta = (now - ts).total_seconds()
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta / 60)}m ago"
        return f"{int(delta / 3600)}h ago"

    def _preview_value(value: Any, max_len: int = 120) -> str:
        """Format a memory value for display, truncating if needed."""
        if value is None:
            return "null (not yet set)"
        if isinstance(value, list):
            preview = str(value)[:max_len]
            return f"[{len(value)} items] {preview}"
        if isinstance(value, dict):
            preview = str(value)[:max_len]
            return f"{{{len(value)} keys}} {preview}"
        s = str(value)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s

    def _build_preamble(
        runtime: AgentHost,
    ) -> dict[str, Any]:
        """Build the lightweight preamble: status, node, elapsed, iteration.

        Always cheap to compute. Returns a dict with:
        - status: idle / running / waiting_for_input
        - current_node, current_iteration, elapsed_seconds (when applicable)
        - pending_question (when waiting)
        - _active_execs (internal, stripped before return)
        """

        stream_id = runtime.stream_id
        reg = runtime.get_worker_registration(stream_id)
        if reg is None:
            return {"status": "not_loaded"}

        preamble: dict[str, Any] = {}

        # Execution state
        active_execs = []
        for ep_id, stream in reg.streams.items():
            for exec_id in stream.active_execution_ids:
                exec_info: dict[str, Any] = {
                    "execution_id": exec_id,
                    "entry_point": ep_id,
                }
                ctx = stream.get_context(exec_id)
                if ctx:
                    elapsed = (datetime.now() - ctx.started_at).total_seconds()
                    exec_info["elapsed_seconds"] = round(elapsed, 1)
                active_execs.append(exec_info)
        preamble["_active_execs"] = active_execs

        if not active_execs:
            preamble["status"] = "idle"
        else:
            waiting_nodes = []
            for _ep_id, stream in reg.streams.items():
                waiting_nodes.extend(stream.get_waiting_nodes())
            preamble["status"] = "waiting_for_input" if waiting_nodes else "running"
            if active_execs:
                preamble["elapsed_seconds"] = active_execs[0].get("elapsed_seconds", 0)

        # Enrich with EventBus basics (cheap limit=1 queries)
        bus = _get_event_bus()
        if bus:
            if preamble["status"] == "waiting_for_input":
                input_events = bus.get_history(event_type=EventType.CLIENT_INPUT_REQUESTED, limit=1)
                if input_events:
                    prompt = input_events[0].data.get("prompt", "")
                    if prompt:
                        preamble["pending_question"] = prompt[:200]

            edge_events = bus.get_history(event_type=EventType.NODE_RETRY, limit=1)
            if edge_events:
                target = edge_events[0].data.get("target_node")
                if target:
                    preamble["current_node"] = target

            iter_events = bus.get_history(event_type=EventType.NODE_LOOP_ITERATION, limit=1)
            if iter_events:
                preamble["current_iteration"] = iter_events[0].data.get("iteration")

        return preamble

    def _detect_red_flags(bus: EventBus) -> int:
        """Count issue categories with cheap limit=1 queries."""
        count = 0
        for evt_type in (
            EventType.NODE_STALLED,
            EventType.NODE_TOOL_DOOM_LOOP,
            EventType.CONSTRAINT_VIOLATION,
        ):
            if bus.get_history(event_type=evt_type, limit=1):
                count += 1
        return count

    # Status port the gcu bridge serves /status and /contexts on. Mirrors
    # tools/src/gcu/browser/bridge.py: STATUS_PORT = BRIDGE_PORT + 1.
    # Hard-coded rather than imported so core stays independent of the
    # gcu package layout.
    _GCU_STATUS_PORT = 9230

    async def _build_worker_browsers(runtime: Any) -> dict[str, dict[str, Any]]:
        """Authoritative per-worker browser snapshot from the gcu bridge.

        Each parallel worker gets its own Chrome tab group — the
        worker_id IS the browser profile (see
        ``core/framework/host/worker.py``). The gcu bridge already
        exposes a plain HTTP status server in the gcu subprocess; we
        ask it for ``/contexts`` and intersect with the colony's active
        workers so the queen sees one entry per live worker that owns a
        tab group. Going over the bridge's own HTTP endpoint avoids
        adding a new MCP tool (which would clutter every worker's tool
        list) while still reading from the single source of truth.

        Returns ``{worker_id: {groupId, activeTab, tabs}}``. Empty when
        no worker has a browser session, when the bridge isn't running,
        or when the fetch fails — all expected non-browser cases, so
        the caller can use a falsy check without special-casing errors.
        """
        # Gather currently-active worker IDs so we filter out the queen's
        # own profile and any stale tab groups for finished workers.
        active_workers: set[str] = set()
        try:
            workers = getattr(runtime, "_workers", None) or {}
            for wid, w in workers.items():
                if getattr(w, "is_active", False):
                    active_workers.add(wid)
        except Exception:
            return {}
        if not active_workers:
            return {}

        # Cheap HTTP GET to the gcu bridge's status server. Tight timeout
        # because /contexts may call into the extension to enumerate tabs
        # per group, and a hung extension shouldn't stall the queen's
        # status check. httpx is already a project dependency.
        try:
            import httpx

            async with httpx.AsyncClient(timeout=2.0) as http:
                resp = await http.get(f"http://127.0.0.1:{_GCU_STATUS_PORT}/contexts")
                if resp.status_code != 200:
                    return {}
                parsed = resp.json()
        except Exception:
            return {}

        if not isinstance(parsed, dict):
            return {}

        contexts = parsed.get("contexts") or []
        out: dict[str, dict[str, Any]] = {}
        for ctx in contexts:
            if not isinstance(ctx, dict):
                continue
            profile = ctx.get("profile")
            if not isinstance(profile, str) or profile not in active_workers:
                continue
            out[profile] = {
                "groupId": ctx.get("groupId"),
                "activeTab": ctx.get("activeTab"),
                "tabs": ctx.get("tabs") or [],
            }
        return out

    def _format_summary(
        preamble: dict[str, Any],
        red_flags: int,
        worker_browsers: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        """Generate a 1-2 sentence prose summary from the preamble."""
        status = preamble["status"]

        if status == "idle":
            return "Worker is idle. No active executions."
        if status == "not_loaded":
            return "No worker loaded."
        if status == "waiting_for_input":
            q = preamble.get("pending_question", "")
            if q:
                return f'Worker is waiting for input: "{q}"'
            return "Worker is waiting for input."

        # Running
        parts = []
        elapsed = preamble.get("elapsed_seconds", 0)
        parts.append(f"Worker is running ({_format_elapsed(elapsed)})")

        node = preamble.get("current_node")
        iteration = preamble.get("current_iteration")
        if node:
            node_part = f"Currently in {node}"
            if iteration is not None:
                node_part += f", iteration {iteration}"
            parts.append(node_part)

        if red_flags:
            parts.append(f"{red_flags} issue type(s) detected — use focus='issues' for details")
        else:
            parts.append("No issues detected")

        # Latest subagent progress (if any delegation is in flight)
        bus = _get_event_bus()
        if bus:
            sa_reports = bus.get_history(event_type=EventType.SUBAGENT_REPORT, limit=1)
            if sa_reports:
                latest = sa_reports[0]
                sa_msg = str(latest.data.get("message", ""))[:200]
                ago = _format_time_ago(latest.timestamp)
                parts.append(f"Latest subagent update ({ago}): {sa_msg}")

        # Per-worker browser sessions: surface a one-line hint when any
        # parallel worker has its own tab group. Empty for non-browser
        # colonies, so it adds no noise to the summary.
        if worker_browsers:
            parts.append(f"{len(worker_browsers)} worker(s) on isolated browser tab groups (focus='full' for per-worker tabs)")

        return ". ".join(parts) + "."

    def _format_activity(bus: EventBus, preamble: dict[str, Any], last_n: int) -> str:
        """Format current activity: node, iteration, transitions, LLM output."""
        lines = []

        node = preamble.get("current_node", "unknown")
        iteration = preamble.get("current_iteration")
        elapsed = preamble.get("elapsed_seconds", 0)
        node_desc = f"Current node: {node}"
        if iteration is not None:
            node_desc += f" (iteration {iteration}, {_format_elapsed(elapsed)} elapsed)"
        else:
            node_desc += f" ({_format_elapsed(elapsed)} elapsed)"
        lines.append(node_desc)

        # Latest LLM output snippet
        text_events = bus.get_history(event_type=EventType.LLM_TEXT_DELTA, limit=1)
        if text_events:
            snapshot = text_events[0].data.get("snapshot", "") or ""
            snippet = snapshot[-300:].strip()
            if snippet:
                # Show last meaningful chunk
                lines.append(f'Last LLM output: "{snippet}"')

        # Recent node transitions
        edges = bus.get_history(event_type=EventType.NODE_RETRY, limit=last_n)
        if edges:
            lines.append("")
            lines.append("Recent transitions:")
            for evt in edges:
                src = evt.data.get("source_node", "?")
                tgt = evt.data.get("target_node", "?")
                cond = evt.data.get("edge_condition", "")
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {src} -> {tgt} ({cond}, {ago})")

        return "\n".join(lines)

    async def _format_memory(runtime: AgentHost) -> str:
        """Format the worker's shared buffer snapshot and recent changes."""
        from framework.host.isolation import IsolationLevel

        lines = []
        active_streams = runtime.get_active_streams()

        if not active_streams:
            return "Worker has no active executions. No buffer state to inspect."

        # Read buffer state from the first active execution
        stream_info = active_streams[0]
        exec_ids = stream_info.get("active_execution_ids", [])
        stream_id = stream_info.get("stream_id", "")
        if not exec_ids:
            return "No active execution found."

        exec_id = exec_ids[0]
        buf = runtime.state_manager.create_buffer(exec_id, stream_id, IsolationLevel.SHARED)
        state = await buf.read_all()

        if not state:
            lines.append("Worker's shared buffer is empty.")
        else:
            lines.append(f"Worker's shared buffer ({len(state)} keys):")
            for key, value in state.items():
                lines.append(f"  {key}: {_preview_value(value)}")

        # Recent state changes
        changes = runtime.state_manager.get_recent_changes(limit=5)
        if changes:
            lines.append("")
            lines.append(f"Recent changes (last {len(changes)}):")
            for change in reversed(changes):  # most recent first
                from datetime import datetime

                ago = _format_time_ago(datetime.fromtimestamp(change.timestamp, tz=UTC))
                if change.old_value is None:
                    lines.append(f"  {change.key} set ({ago})")
                else:
                    old_preview = _preview_value(change.old_value, 40)
                    new_preview = _preview_value(change.new_value, 40)
                    lines.append(f"  {change.key}: {old_preview} -> {new_preview} ({ago})")

        return "\n".join(lines)

    def _format_tools(bus: EventBus, last_n: int) -> str:
        """Format running and recent tool calls."""
        lines = []

        # Running tools (started but not yet completed)
        tool_started = bus.get_history(event_type=EventType.TOOL_CALL_STARTED, limit=last_n * 2)
        tool_completed = bus.get_history(event_type=EventType.TOOL_CALL_COMPLETED, limit=last_n * 2)
        completed_ids = {evt.data.get("tool_use_id") for evt in tool_completed if evt.data.get("tool_use_id")}
        running = [evt for evt in tool_started if evt.data.get("tool_use_id") and evt.data.get("tool_use_id") not in completed_ids]

        if running:
            names = [evt.data.get("tool_name", "?") for evt in running]
            lines.append(f"{len(running)} tool(s) running: {', '.join(names)}.")
            for evt in running:
                name = evt.data.get("tool_name", "?")
                node = evt.node_id or "?"
                ago = _format_time_ago(evt.timestamp)
                inp = str(evt.data.get("tool_input", ""))[:150]
                lines.append(f"  {name} ({node}, started {ago})")
                if inp:
                    lines.append(f"    Input: {inp}")
        else:
            lines.append("No tools currently running.")

        # Recent completed calls
        if tool_completed:
            lines.append("")
            lines.append(f"Recent calls (last {min(last_n, len(tool_completed))}):")
            for evt in tool_completed[:last_n]:
                name = evt.data.get("tool_name", "?")
                node = evt.node_id or "?"
                is_error = bool(evt.data.get("is_error"))
                status = "error" if is_error else "ok"
                duration = evt.data.get("duration_s")
                dur_str = f", {duration:.1f}s" if duration else ""
                lines.append(f"  {name} ({node}) — {status}{dur_str}")
                result_text = evt.data.get("result", "")
                if result_text:
                    preview = str(result_text)[:300].replace("\n", " ")
                    lines.append(f"    Result: {preview}")
        else:
            lines.append("No recent tool calls.")

        return "\n".join(lines)

    def _format_issues(bus: EventBus) -> str:
        """Format retries, stalls, doom loops, and constraint violations."""
        lines = []
        total = 0

        # Retries
        retries = bus.get_history(event_type=EventType.NODE_RETRY, limit=20)
        if retries:
            total += len(retries)
            lines.append(f"{len(retries)} retry event(s):")
            for evt in retries[:5]:
                node = evt.node_id or "?"
                count = evt.data.get("retry_count", "?")
                error = evt.data.get("error", "")[:120]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {node} (attempt {count}, {ago}): {error}")

        # Stalls
        stalls = bus.get_history(event_type=EventType.NODE_STALLED, limit=5)
        if stalls:
            total += len(stalls)
            lines.append(f"{len(stalls)} stall(s):")
            for evt in stalls:
                node = evt.node_id or "?"
                reason = evt.data.get("reason", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {node} ({ago}): {reason}")

        # Doom loops
        doom_loops = bus.get_history(event_type=EventType.NODE_TOOL_DOOM_LOOP, limit=5)
        if doom_loops:
            total += len(doom_loops)
            lines.append(f"{len(doom_loops)} tool doom loop(s):")
            for evt in doom_loops:
                node = evt.node_id or "?"
                desc = evt.data.get("description", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {node} ({ago}): {desc}")

        # Constraint violations
        violations = bus.get_history(event_type=EventType.CONSTRAINT_VIOLATION, limit=5)
        if violations:
            total += len(violations)
            lines.append(f"{len(violations)} constraint violation(s):")
            for evt in violations:
                cid = evt.data.get("constraint_id", "?")
                desc = evt.data.get("description", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  {cid} ({ago}): {desc}")

        if total == 0:
            return "No issues detected. No retries, stalls, or constraint violations."

        header = f"{total} issue(s) detected."
        return header + "\n\n" + "\n".join(lines)

    async def _format_progress(runtime: AgentHost, bus: EventBus) -> str:
        """Format goal progress, token consumption, and execution outcomes."""
        lines = []

        # Goal progress
        try:
            progress = await runtime.get_goal_progress()
            if progress:
                criteria = progress.get("criteria_status", {})
                if criteria:
                    met = sum(1 for c in criteria.values() if c.get("met"))
                    total_c = len(criteria)
                    lines.append(f"Goal: {met}/{total_c} criteria met.")
                    for cid, cdata in criteria.items():
                        marker = "met" if cdata.get("met") else "not met"
                        desc = cdata.get("description", cid)
                        evidence = cdata.get("evidence", [])
                        ev_str = f" — {evidence[0]}" if evidence else ""
                        lines.append(f"  [{marker}] {desc}{ev_str}")
                rec = progress.get("recommendation")
                if rec:
                    lines.append(f"Recommendation: {rec}.")
        except Exception:
            lines.append("Goal progress unavailable.")

        # Token summary
        llm_events = bus.get_history(event_type=EventType.LLM_TURN_COMPLETE, limit=200)
        if llm_events:
            total_in = sum(evt.data.get("input_tokens", 0) or 0 for evt in llm_events)
            total_out = sum(evt.data.get("output_tokens", 0) or 0 for evt in llm_events)
            total_tok = total_in + total_out
            lines.append("")
            lines.append(f"Tokens: {len(llm_events)} LLM turns, {total_tok:,} total ({total_in:,} in + {total_out:,} out).")

        # Execution outcomes
        exec_completed = bus.get_history(event_type=EventType.EXECUTION_COMPLETED, limit=5)
        exec_failed = bus.get_history(event_type=EventType.EXECUTION_FAILED, limit=5)
        completed_n = len(exec_completed)
        failed_n = len(exec_failed)
        active_n = len(runtime.get_active_streams())
        lines.append(f"Executions: {completed_n} completed, {failed_n} failed" + (f" ({active_n} active)." if active_n else "."))
        if exec_failed:
            for evt in exec_failed[:3]:
                error = evt.data.get("error", "")[:150]
                ago = _format_time_ago(evt.timestamp)
                lines.append(f"  Failed ({ago}): {error}")

        return "\n".join(lines)

    def _build_full_json(
        runtime: AgentHost,
        bus: EventBus,
        preamble: dict[str, Any],
        last_n: int,
    ) -> dict[str, Any]:
        """Build the legacy full JSON response (backward compat for focus='full')."""

        stream_id = runtime.stream_id
        goal = runtime.goal
        result: dict[str, Any] = {
            "worker_colony_id": stream_id,
            "worker_goal": getattr(goal, "name", stream_id),
            "status": preamble["status"],
        }

        active_execs = preamble.get("_active_execs", [])
        if active_execs:
            result["active_executions"] = active_execs
        if preamble.get("pending_question"):
            result["pending_question"] = preamble["pending_question"]

        _idle = runtime.agent_idle_seconds
        result["agent_idle_seconds"] = round(_idle, 1) if _idle != float("inf") else -1

        for key in ("current_node", "current_iteration"):
            if key in preamble:
                result[key] = preamble[key]

        # Running + completed tool calls
        tool_started = bus.get_history(event_type=EventType.TOOL_CALL_STARTED, limit=last_n * 2)
        tool_completed = bus.get_history(event_type=EventType.TOOL_CALL_COMPLETED, limit=last_n * 2)
        completed_ids = {evt.data.get("tool_use_id") for evt in tool_completed if evt.data.get("tool_use_id")}
        running = [evt for evt in tool_started if evt.data.get("tool_use_id") and evt.data.get("tool_use_id") not in completed_ids]
        if running:
            result["running_tools"] = [
                {
                    "tool": evt.data.get("tool_name"),
                    "node": evt.node_id,
                    "started_at": evt.timestamp.isoformat(),
                    "input_preview": str(evt.data.get("tool_input", ""))[:200],
                }
                for evt in running
            ]
        if tool_completed:
            recent_calls = []
            for evt in tool_completed[:last_n]:
                entry: dict[str, Any] = {
                    "tool": evt.data.get("tool_name"),
                    "error": bool(evt.data.get("is_error")),
                    "node": evt.node_id,
                    "time": evt.timestamp.isoformat(),
                }
                result_text = evt.data.get("result", "")
                if result_text:
                    entry["result_preview"] = str(result_text)[:300]
                recent_calls.append(entry)
            result["recent_tool_calls"] = recent_calls

        # Node transitions
        edges = bus.get_history(event_type=EventType.NODE_RETRY, limit=last_n)
        if edges:
            result["node_transitions"] = [
                {
                    "from": evt.data.get("source_node"),
                    "to": evt.data.get("target_node"),
                    "condition": evt.data.get("edge_condition"),
                    "time": evt.timestamp.isoformat(),
                }
                for evt in edges
            ]

        # Retries
        retries = bus.get_history(event_type=EventType.NODE_RETRY, limit=last_n)
        if retries:
            result["retries"] = [
                {
                    "node": evt.node_id,
                    "retry_count": evt.data.get("retry_count"),
                    "error": evt.data.get("error", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
                for evt in retries
            ]

        # Stalls and doom loops
        stalls = bus.get_history(event_type=EventType.NODE_STALLED, limit=5)
        doom_loops = bus.get_history(event_type=EventType.NODE_TOOL_DOOM_LOOP, limit=5)
        issues = []
        for evt in stalls:
            issues.append(
                {
                    "type": "stall",
                    "node": evt.node_id,
                    "reason": evt.data.get("reason", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
            )
        for evt in doom_loops:
            issues.append(
                {
                    "type": "tool_doom_loop",
                    "node": evt.node_id,
                    "description": evt.data.get("description", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
            )
        if issues:
            result["issues"] = issues

        # Subagent activity (in-flight progress from delegated subagents)
        sa_reports = bus.get_history(event_type=EventType.SUBAGENT_REPORT, limit=last_n)
        if sa_reports:
            result["subagent_activity"] = [
                {
                    "subagent": evt.data.get("subagent_id"),
                    "message": str(evt.data.get("message", ""))[:300],
                    "time": evt.timestamp.isoformat(),
                }
                for evt in sa_reports[:last_n]
            ]

        # Constraint violations
        violations = bus.get_history(event_type=EventType.CONSTRAINT_VIOLATION, limit=5)
        if violations:
            result["constraint_violations"] = [
                {
                    "constraint": evt.data.get("constraint_id"),
                    "description": evt.data.get("description", "")[:200],
                    "time": evt.timestamp.isoformat(),
                }
                for evt in violations
            ]

        # Token summary
        llm_events = bus.get_history(event_type=EventType.LLM_TURN_COMPLETE, limit=200)
        if llm_events:
            total_in = sum(evt.data.get("input_tokens", 0) or 0 for evt in llm_events)
            total_out = sum(evt.data.get("output_tokens", 0) or 0 for evt in llm_events)
            result["token_summary"] = {
                "llm_turns": len(llm_events),
                "input_tokens": total_in,
                "output_tokens": total_out,
                "total_tokens": total_in + total_out,
            }

        # Execution outcomes
        exec_completed = bus.get_history(event_type=EventType.EXECUTION_COMPLETED, limit=5)
        exec_failed = bus.get_history(event_type=EventType.EXECUTION_FAILED, limit=5)
        if exec_completed or exec_failed:
            result["execution_outcomes"] = []
            for evt in exec_completed:
                result["execution_outcomes"].append(
                    {
                        "outcome": "completed",
                        "execution_id": evt.execution_id,
                        "time": evt.timestamp.isoformat(),
                    }
                )
            for evt in exec_failed:
                result["execution_outcomes"].append(
                    {
                        "outcome": "failed",
                        "execution_id": evt.execution_id,
                        "error": evt.data.get("error", "")[:200],
                        "time": evt.timestamp.isoformat(),
                    }
                )

        return result

    async def get_worker_status(focus: str | None = None, last_n: int = 20) -> str:
        """Check on the loaded graph with progressive disclosure.

        Without arguments, returns a brief prose summary. Use ``focus`` to
        drill into specifics: activity, memory, tools, issues, progress,
        or full (JSON dump).

        Args:
            focus: Aspect to inspect (activity/memory/tools/issues/progress/full).
                   Omit for a brief summary.
            last_n: Recent events per category (default 20). For activity, tools, full.
        """
        import time as _time

        # --- Tiered cooldown ---
        # summary is free, detail has 10s, full keeps 30s
        now = _time.monotonic()
        if focus == "full":
            cooldown = _COOLDOWN_FULL
            tier = "full"
        elif focus is None:
            cooldown = 0.0
            tier = "summary"
        else:
            cooldown = _COOLDOWN_DETAIL
            tier = "detail"

        elapsed_since = now - _status_last_called.get(tier, 0.0)
        if elapsed_since < cooldown:
            remaining = int(cooldown - elapsed_since)
            return json.dumps(
                {
                    "status": "cooldown",
                    "message": (f"Status '{focus or 'summary'}' was checked {int(elapsed_since)}s ago. Wait {remaining}s or try a different focus."),
                }
            )
        _status_last_called[tier] = now

        # --- Runtime check ---
        runtime = _get_runtime()
        if runtime is None:
            return "No colony running."

        preamble = _build_preamble(runtime)

        bus = _get_event_bus()

        try:
            if focus is None:
                # Default: brief prose summary
                red_flags = _detect_red_flags(bus) if bus else 0
                worker_browsers = await _build_worker_browsers(runtime)
                return _format_summary(preamble, red_flags, worker_browsers)

            if bus is None:
                return f"Worker is {preamble['status']}. EventBus unavailable — only basic status returned."

            if focus == "activity":
                return _format_activity(bus, preamble, last_n)
            elif focus == "memory":
                return await _format_memory(runtime)
            elif focus == "tools":
                return _format_tools(bus, last_n)
            elif focus == "issues":
                return _format_issues(bus)
            elif focus == "progress":
                return await _format_progress(runtime, bus)
            elif focus == "full":
                result = _build_full_json(runtime, bus, preamble, last_n)
                # Also include goal progress in full dump
                try:
                    progress = await runtime.get_goal_progress()
                    if progress:
                        result["goal_progress"] = progress
                except Exception:
                    pass
                # Authoritative per-worker browser snapshot (empty when
                # no parallel worker has started a tab group).
                wb = await _build_worker_browsers(runtime)
                if wb:
                    result["worker_browsers"] = wb
                return json.dumps(result, default=str, ensure_ascii=False)
            else:
                return f"Unknown focus '{focus}'. Valid options: activity, memory, tools, issues, progress, full."
        except Exception as exc:
            logger.exception("get_worker_status error")
            return f"Error retrieving status: {exc}"

    _status_tool = Tool(
        name="get_worker_status",
        description=(
            "Check on the loaded graph. Returns a brief prose summary by default. "
            "Use 'focus' to drill into specifics:\n"
            "- activity: current node, transitions, latest LLM output\n"
            "- memory: worker's accumulated buffer state\n"
            "- tools: running and recent tool calls\n"
            "- issues: retries, stalls, constraint violations\n"
            "- progress: goal criteria, token consumption\n"
            "- full: everything as JSON\n"
            "For a PLAYBOOK (run_playbook), use get_playbook_status(run_id=...) "
            "instead — it reports the convergence run's progress by run_id."
        ),
        parameters={
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": ["activity", "memory", "tools", "issues", "progress", "full"],
                    "description": ("Aspect to inspect. Omit for a brief summary."),
                },
                "last_n": {
                    "type": "integer",
                    "description": ("Recent events per category (default 20). Only for activity, tools, full."),
                },
            },
            "required": [],
        },
    )
    registry.register("get_worker_status", _status_tool, lambda inputs: get_worker_status(**inputs))
    tools_registered += 1

    # --- inject_message -------------------------------------------------------

    async def inject_message(content: str) -> str:
        """Send a message to the running graph.

        Injects the message into the worker's active node conversation.
        Use this to relay user instructions to the worker.
        """
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No colony running in this session."})

        stream_id = runtime.stream_id
        reg = runtime.get_worker_registration(stream_id)
        if reg is None:
            return json.dumps({"error": "Colony not found"})

        # Prefer nodes that are actively waiting (e.g. escalation receivers
        # blocked on queen guidance) over the main event-loop node.
        for stream in reg.streams.values():
            waiting = stream.get_waiting_nodes()
            if waiting:
                target_node_id = waiting[0]["node_id"]
                ok = await stream.inject_input(target_node_id, content, is_client_input=True)
                if ok:
                    return json.dumps(
                        {
                            "status": "delivered",
                            "node_id": target_node_id,
                            "content_preview": content[:100],
                        }
                    )

        # Fallback: inject into any injectable node
        for stream in reg.streams.values():
            injectable = stream.get_injectable_nodes()
            if injectable:
                target_node_id = injectable[0]["node_id"]
                ok = await stream.inject_input(target_node_id, content, is_client_input=True)
                if ok:
                    return json.dumps(
                        {
                            "status": "delivered",
                            "node_id": target_node_id,
                            "content_preview": content[:100],
                        }
                    )

        return json.dumps(
            {
                "error": "No active graph node found — graph may be idle.",
            }
        )

    _inject_tool = Tool(
        name="inject_message",
        description=(
            "Send a message to the running graph. The message is injected "
            "into the graph's active node conversation. Use this to relay user "
            "instructions or concerns. The graph must be running."
        ),
        parameters={
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Message content to send to the graph",
                },
            },
            "required": ["content"],
        },
    )
    registry.register("inject_message", _inject_tool, lambda inputs: inject_message(**inputs))
    tools_registered += 1

    # --- list_credentials -----------------------------------------------------

    async def list_credentials(credential_id: str = "") -> str:
        """List all authorized credentials (Aden OAuth + local encrypted store).

        Returns credential IDs, aliases, status, and identity metadata.
        Never returns secret values. Optionally filter by credential_id.
        """
        # Load shell config vars into os.environ — same first step as check-agent.
        # Ensures keys set in ~/.zshrc/~/.bashrc are visible to is_available() checks.
        try:
            from framework.credentials.validation import ensure_credential_key_env

            ensure_credential_key_env()
        except Exception:
            pass

        try:
            # Primary: CredentialStoreAdapter sees both Aden OAuth and local accounts
            from aden_tools.credentials import CredentialStoreAdapter

            store = CredentialStoreAdapter.default()
            all_accounts = store.get_all_account_info()

            # Filter by credential_id / provider if requested.
            # A spec name like "gmail_oauth" maps to provider "google" via
            # credential_id field — resolve that alias before filtering.
            if credential_id:
                try:
                    from aden_tools.credentials import CREDENTIAL_SPECS

                    spec = CREDENTIAL_SPECS.get(credential_id)
                    resolved_provider = (spec.credential_id or credential_id) if spec else credential_id
                except Exception:
                    resolved_provider = credential_id
                all_accounts = [
                    a
                    for a in all_accounts
                    if a.get("credential_id", "").startswith(credential_id) or a.get("provider", "") in (credential_id, resolved_provider)
                ]

            return json.dumps(
                {
                    "count": len(all_accounts),
                    "credentials": all_accounts,
                },
                default=str,
            )
        except ImportError:
            pass
        except Exception as e:
            return json.dumps({"error": f"Failed to list credentials: {e}"})

        # Fallback: local encrypted store only
        try:
            from framework.credentials.local.models import LocalAccountInfo
            from framework.credentials.local.registry import LocalCredentialRegistry
            from framework.credentials.storage import EncryptedFileStorage

            registry = LocalCredentialRegistry.default()
            accounts = registry.list_accounts(
                credential_id=credential_id or None,
            )

            # Also include flat-file credentials saved by the GUI (no "/" separator).
            # LocalCredentialRegistry.list_accounts() skips these — read them directly.
            seen_cred_ids = {info.credential_id for info in accounts}
            storage = EncryptedFileStorage()
            for storage_id in storage.list_all():
                if "/" in storage_id:
                    continue  # already handled by LocalCredentialRegistry above
                if credential_id and storage_id != credential_id:
                    continue
                if storage_id in seen_cred_ids:
                    continue
                try:
                    cred_obj = storage.load(storage_id)
                except Exception:
                    continue
                if cred_obj is None:
                    continue
                accounts.append(
                    LocalAccountInfo(
                        credential_id=storage_id,
                        alias="default",
                        status="unknown",
                        identity=cred_obj.identity,
                        last_validated=cred_obj.last_refreshed,
                        created_at=cred_obj.created_at,
                    )
                )

            credentials = []
            for info in accounts:
                entry: dict[str, Any] = {
                    "credential_id": info.credential_id,
                    "alias": info.alias,
                    "storage_id": info.storage_id,
                    "status": info.status,
                    "created_at": info.created_at.isoformat() if info.created_at else None,
                    "last_validated": (info.last_validated.isoformat() if info.last_validated else None),
                }
                identity = info.identity.to_dict()
                if identity:
                    entry["identity"] = identity
                credentials.append(entry)

            return json.dumps(
                {
                    "count": len(credentials),
                    "credentials": credentials,
                    "location": "~/.hive/credentials",
                },
                default=str,
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to list credentials: {e}"})

    _list_creds_tool = Tool(
        name="list_credentials",
        description=(
            "List all authorized credentials in the local store. Returns credential IDs, "
            "aliases, status (active/failed/unknown), and identity metadata — never secret "
            "values. Optionally filter by credential_id (e.g. 'brave_search')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "credential_id": {
                    "type": "string",
                    "description": ("Filter to a specific credential type (e.g. 'brave_search'). Omit to list all credentials."),
                },
            },
            "required": [],
        },
    )
    registry.register("list_credentials", _list_creds_tool, lambda inputs: list_credentials(**inputs))
    tools_registered += 1

    # --- list_worker_questions / reply_to_worker ------------------------------
    #
    # Workers escalate via the framework-level ``escalate`` tool, which emits
    # ESCALATION_REQUESTED events stamped with a fresh request_id. The queen's
    # colony-scoped subscription (see queen_orchestrator._on_worker_escalation)
    # records each pending escalation on ``session.pending_escalations``,
    # keyed by request_id, so multiple concurrent waiters stay addressable.
    # These tools read and drain that inbox.

    async def list_worker_questions() -> str:
        """List pending worker escalations awaiting a queen reply."""
        pending = getattr(session, "pending_escalations", None) or {}
        # Copy values and trim context to keep the tool return compact.
        entries = []
        now = time.time()
        for entry in pending.values():
            entries.append(
                {
                    "request_id": entry.get("request_id"),
                    "worker_id": entry.get("worker_id"),
                    "colony_id": entry.get("colony_id"),
                    "node_id": entry.get("node_id"),
                    "reason": entry.get("reason"),
                    "context_preview": (entry.get("context") or "")[:300],
                    "waiting_seconds": round(now - float(entry.get("opened_at") or now), 1),
                }
            )
        return json.dumps({"count": len(entries), "pending": entries})

    _list_questions_tool = Tool(
        name="list_worker_questions",
        description=(
            "List all worker escalations currently awaiting your reply. "
            "Each entry has a request_id that you pass to reply_to_worker() "
            "to unblock the specific worker that asked."
        ),
        parameters={"type": "object", "properties": {}},
    )
    registry.register(
        "list_worker_questions",
        _list_questions_tool,
        lambda inputs: list_worker_questions(),
    )
    tools_registered += 1

    async def reply_to_worker(request_id: str, reply: str) -> str:
        """Reply to a specific worker escalation by request_id."""
        runtime = _get_runtime()
        if runtime is None:
            return json.dumps({"error": "No colony running in this session."})

        pending = getattr(session, "pending_escalations", None)
        if pending is None:
            return json.dumps({"error": "Session has no escalation inbox."})

        entry = pending.get(request_id)
        if entry is None:
            return json.dumps(
                {
                    "error": "Unknown request_id. Call list_worker_questions() to see currently pending escalations.",
                    "request_id": request_id,
                }
            )

        worker_id = entry.get("worker_id")
        if not worker_id:
            return json.dumps({"error": "Escalation entry is missing worker_id.", "request_id": request_id})

        # Format the reply so the waiting worker's conversation shows
        # it as a queen handoff rather than a raw user message.
        reply_text = f"[QUEEN_REPLY] request_id={request_id}\n{reply}"
        try:
            delivered = await runtime.inject_input(worker_id, reply_text)
        except Exception as e:
            return json.dumps({"error": f"Failed to inject reply: {e}"})

        # Drop the entry regardless of delivery — a failed delivery
        # usually means the worker already terminated, in which case
        # it cannot be unblocked and the entry should not linger.
        pending.pop(request_id, None)

        return json.dumps(
            {
                "status": "delivered" if delivered else "worker_not_active",
                "worker_id": worker_id,
                "request_id": request_id,
            }
        )

    _reply_tool = Tool(
        name="reply_to_worker",
        description=(
            "Reply to a specific worker escalation. The reply is injected "
            "into the identified worker's conversation so it can resume. "
            "Use list_worker_questions() to discover pending request_ids."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "The escalation request_id from list_worker_questions.",
                },
                "reply": {
                    "type": "string",
                    "description": "Guidance or answer text to hand back to the worker.",
                },
            },
            "required": ["request_id", "reply"],
        },
    )
    registry.register("reply_to_worker", _reply_tool, lambda inputs: reply_to_worker(**inputs))
    tools_registered += 1

    # --- set_trigger -----------------------------------------------------------

    async def set_trigger(
        trigger_id: str,
        trigger_type: str | None = None,
        trigger_config: dict | None = None,
        task: str | None = None,
    ) -> str:
        """Activate a trigger so it fires periodically into the queen."""
        if trigger_id in getattr(session, "active_trigger_ids", set()):
            return json.dumps({"error": f"Trigger '{trigger_id}' is already active."})

        # Look up existing or create new
        available = getattr(session, "available_triggers", {})
        tdef = available.get(trigger_id)

        if tdef is None:
            if trigger_type and trigger_config:
                from framework.host.triggers import TriggerDefinition

                tdef = TriggerDefinition(
                    id=trigger_id,
                    trigger_type=trigger_type,
                    trigger_config=trigger_config,
                )
                available[trigger_id] = tdef
            else:
                return json.dumps(
                    {"error": (f"Trigger '{trigger_id}' not found. Provide trigger_type and trigger_config to create a custom trigger.")}
                )

        # Apply task override if provided
        if task:
            tdef.task = task

        # Task is mandatory before activation
        if not tdef.task:
            return json.dumps(
                {"error": f"Trigger '{trigger_id}' has no task configured. Set a task describing what the worker should do when this trigger fires."}
            )

        # Use provided overrides if given
        t_type = trigger_type or tdef.trigger_type
        t_config = trigger_config or tdef.trigger_config
        if trigger_type:
            tdef.trigger_type = t_type
        if trigger_config:
            tdef.trigger_config = t_config

        # Validate and activate by type
        if t_type == "webhook":
            path = t_config.get("path", "").strip()
            if not path or not path.startswith("/"):
                return json.dumps({"error": ("Webhook trigger requires 'path' starting with '/' in trigger_config (e.g. '/hooks/github').")})
            valid_methods = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
            methods = t_config.get("methods", ["POST"])
            invalid = [m.upper() for m in methods if m.upper() not in valid_methods]
            if invalid:
                return json.dumps({"error": f"Invalid HTTP methods: {invalid}. Valid: {sorted(valid_methods)}"})

            try:
                await _start_trigger_webhook(session, trigger_id, tdef)
            except Exception as e:
                return json.dumps({"error": f"Failed to start webhook trigger: {e}"})

            tdef.enabled = True
            session.active_trigger_ids.add(trigger_id)
            await _persist_active_triggers(session, session_id)
            _save_trigger_to_agent(session, trigger_id, tdef)
            await _publish_trigger_activated(trigger_id, t_type, t_config, tdef)
            port = int(t_config.get("port", 8090))
            return json.dumps(
                {
                    "status": "activated",
                    "trigger_id": trigger_id,
                    "trigger_type": t_type,
                    "webhook_url": f"http://127.0.0.1:{port}{path}",
                }
            )

        if t_type != "timer":
            return json.dumps({"error": f"Unsupported trigger type: {t_type}"})

        cron_expr = t_config.get("cron")
        interval = t_config.get("interval_minutes")
        if cron_expr:
            try:
                from croniter import croniter

                if not croniter.is_valid(cron_expr):
                    return json.dumps({"error": f"Invalid cron expression: {cron_expr}"})
            except ImportError:
                return json.dumps({"error": "croniter package not installed — cannot validate cron expression."})
        elif interval:
            if not isinstance(interval, (int, float)) or interval <= 0:
                return json.dumps({"error": f"interval_minutes must be > 0, got {interval}"})
        else:
            return json.dumps({"error": "Timer trigger needs 'cron' or 'interval_minutes' in trigger_config."})

        try:
            await _start_trigger_timer(session, trigger_id, tdef)
        except Exception as e:
            return json.dumps({"error": f"Failed to start trigger timer: {e}"})

        tdef.enabled = True
        session.active_trigger_ids.add(trigger_id)

        # Persist to session state and agent definition
        await _persist_active_triggers(session, session_id)
        _save_trigger_to_agent(session, trigger_id, tdef)
        await _publish_trigger_activated(trigger_id, t_type, t_config, tdef)

        return json.dumps(
            {
                "status": "activated",
                "trigger_id": trigger_id,
                "trigger_type": t_type,
                "trigger_config": t_config,
            }
        )

    _set_trigger_tool = Tool(
        name="set_trigger",
        description=(
            "Activate a trigger (timer) so it fires periodically. "
            "Use trigger_id of an available trigger, or provide trigger_type + trigger_config"
            " to create a custom one. "
            "A task must be configured before activation —"
            " either pre-set on the trigger or provided here."
        ),
        parameters={
            "type": "object",
            "properties": {
                "trigger_id": {
                    "type": "string",
                    "description": ("ID of the trigger to activate (from list_triggers) or a new custom ID"),
                },
                "trigger_type": {
                    "type": "string",
                    "description": "Type of trigger ('timer'). Only needed for custom triggers.",
                },
                "trigger_config": {
                    "type": "object",
                    "description": (
                        "Config for the trigger. Timer: {cron: '*/5 * * * *'} or {interval_minutes: 5}. Only needed for custom triggers."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": (
                        "The task/instructions for the worker when this trigger fires"
                        " (e.g. 'Process inbox emails using saved rules')."
                        " Required if not already configured on the trigger."
                    ),
                },
            },
            "required": ["trigger_id"],
        },
    )
    registry.register("set_trigger", _set_trigger_tool, lambda inputs: set_trigger(**inputs))
    tools_registered += 1

    # --- remove_trigger --------------------------------------------------------

    async def remove_trigger(trigger_id: str) -> str:
        """Deactivate an active trigger."""
        if trigger_id not in getattr(session, "active_trigger_ids", set()):
            return json.dumps({"error": f"Trigger '{trigger_id}' is not active."})

        # Cancel timer task (if timer trigger)
        task = session.active_timer_tasks.pop(trigger_id, None)
        if task and not task.done():
            task.cancel()
        getattr(session, "trigger_next_fire", {}).pop(trigger_id, None)

        # Unsubscribe webhook handler (if webhook trigger)
        webhook_subs = getattr(session, "active_webhook_subs", {})
        if sub_id := webhook_subs.pop(trigger_id, None):
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass

        session.active_trigger_ids.discard(trigger_id)

        # Mark inactive
        available = getattr(session, "available_triggers", {})
        tdef = available.get(trigger_id)
        if tdef:
            tdef.enabled = False

        # Persist to session state and remove from agent definition
        await _persist_active_triggers(session, session_id)
        _remove_trigger_from_agent(session, trigger_id)

        # Emit event
        bus = getattr(session, "event_bus", None)
        if bus:
            await bus.publish(
                AgentEvent(
                    type=EventType.TRIGGER_DEACTIVATED,
                    stream_id="queen",
                    data={
                        "trigger_id": trigger_id,
                        "name": tdef.description or trigger_id if tdef else trigger_id,
                    },
                )
            )

        return json.dumps({"status": "deactivated", "trigger_id": trigger_id})

    _remove_trigger_tool = Tool(
        name="remove_trigger",
        description=("Deactivate an active trigger. The trigger stops firing but remains available for re-activation."),
        parameters={
            "type": "object",
            "properties": {
                "trigger_id": {
                    "type": "string",
                    "description": "ID of the trigger to deactivate",
                },
            },
            "required": ["trigger_id"],
        },
    )
    registry.register("remove_trigger", _remove_trigger_tool, lambda inputs: remove_trigger(**inputs))
    tools_registered += 1

    # --- list_triggers ---------------------------------------------------------

    async def list_triggers() -> str:
        """List all available triggers and their status."""
        available = getattr(session, "available_triggers", {})
        triggers = []
        for tdef in available.values():
            triggers.append(
                {
                    "id": tdef.id,
                    "trigger_type": tdef.trigger_type,
                    "trigger_config": tdef.trigger_config,
                    "description": tdef.description,
                    "task": tdef.task,
                    "enabled": tdef.enabled,
                }
            )
        return json.dumps({"triggers": triggers})

    _list_triggers_tool = Tool(
        name="list_triggers",
        description=("List all available triggers (from the loaded worker) and their active/inactive status."),
        parameters={
            "type": "object",
            "properties": {},
        },
    )
    registry.register("list_triggers", _list_triggers_tool, lambda inputs: list_triggers())
    tools_registered += 1

    # run_playbook — deterministic tracker-reconciliation orchestration.
    # Implemented in its own module to keep this file from growing further.
    from framework.tools.playbook_tools import register_playbook_tools

    tools_registered += register_playbook_tools(registry, session)

    logger.info("Registered %d queen lifecycle tools", tools_registered)
    return tools_registered
