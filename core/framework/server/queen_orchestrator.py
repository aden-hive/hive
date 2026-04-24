"""Queen orchestrator — builds and runs the queen executor.

Extracted from SessionManager._start_queen() to keep session management
and queen orchestration concerns separate.
"""

from __future__ import annotations

import asyncio
import logging
import time as _time_mod
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.agent_loop.internals.types import HookContext, HookResult
    from framework.loader.tool_registry import ToolRegistry
    from framework.server.session_manager import Session

logger = logging.getLogger(__name__)

# Maximum number of unanswered worker escalations the queen's inbox will
# buffer before auto-replying queue_full to new ones.
MAX_PENDING_ESCALATIONS = 32


def install_worker_escalation_routing(
    session: Session,
    *,
    colony_runtime: Any | None = None,
) -> str | None:
    """Install the colony-scoped worker escalation handler on the queen bus.

    Every worker ``escalate()`` call emits ESCALATION_REQUESTED stamped with
    colony_id (by StreamEventBus) and a request_id (by AgentLoop). This
    handler records the escalation in ``session.pending_escalations`` so the
    queen can look it up by request_id later, and surfaces it to the queen
    loop as an addressed [WORKER_ESCALATION] inject.

    When ``colony_runtime`` is provided the subscription is scoped with
    ``filter_colony`` so only escalations from workers in *this* queen's
    colony are delivered — cross-colony leakage is structurally impossible.
    Falls back to the raw session bus when no colony is attached.

    Returns the subscription id (for unsubscribe) or ``None`` on failure.
    """
    from framework.host.event_bus import EventType

    async def _on_worker_escalation(event):
        stream_id = event.stream_id or ""
        # Defensive: ignore any stray non-worker origin (e.g. queen).
        if not stream_id.startswith("worker:"):
            return
        worker_id = stream_id[len("worker:") :]
        data = event.data or {}
        request_id = data.get("request_id")
        reason = str(data.get("reason", "")).strip()
        context_text = str(data.get("context", "")).strip()
        node_label = event.node_id or "unknown_node"

        # Back-pressure: if the queen's inbox is full, auto-reply to the
        # worker so it unblocks instead of wedging forever.
        if len(session.pending_escalations) >= MAX_PENDING_ESCALATIONS:
            runtime = session.colony_runtime
            if runtime is not None and worker_id:
                try:
                    await runtime.inject_input(
                        worker_id,
                        "[QUEEN_REPLY] queue_full — queen inbox saturated; proceed with best judgment or retry later.",
                    )
                except Exception:
                    logger.warning(
                        "Failed to send queue_full reply to worker %s",
                        worker_id,
                        exc_info=True,
                    )
            return

        # Record the pending entry so reply_to_worker can address it.
        if request_id:
            session.pending_escalations[request_id] = {
                "request_id": request_id,
                "worker_id": worker_id,
                "colony_id": event.colony_id,
                "node_id": node_label,
                "reason": reason,
                "context": context_text,
                "opened_at": _time_mod.time(),
            }

        # Surface the escalation to the queen as an addressed
        # [WORKER_ESCALATION] message.
        lines = ["[WORKER_ESCALATION]"]
        if request_id:
            lines.append(f"request_id: {request_id}")
        lines.append(f"worker_id: {worker_id or 'unknown'}")
        lines.append(f"node_id: {node_label}")
        lines.append(f"reason: {reason or 'unspecified'}")
        if context_text:
            lines.append("context:")
            lines.append(context_text)
        if request_id:
            lines.append(
                "Use reply_to_worker(request_id, reply) to unblock, or list_worker_questions() to see all pending."
            )
        else:
            lines.append("No request_id — use inject_message(content=...) to relay guidance manually.")
        handoff = "\n".join(lines)

        # Fallback: if the queen loop has gone away, publish a
        # CLIENT_INPUT_REQUESTED so the human sees the question and the
        # worker does not wedge.
        queen_node = session.queen_executor.node_registry.get("queen") if session.queen_executor is not None else None
        if queen_node is None or not hasattr(queen_node, "inject_event"):
            if session.event_bus is not None:
                # Stream the handoff text so the human sees the worker's
                # question, then request input so the reply input appears.
                await session.event_bus.emit_client_output_delta(
                    stream_id="queen",
                    node_id="queen",
                    content=handoff,
                    snapshot=handoff,
                    execution_id=session.id,
                )
                await session.event_bus.emit_client_input_requested(
                    stream_id="queen",
                    node_id="queen",
                    execution_id=session.id,
                )
            return

        await queen_node.inject_event(handoff, is_client_input=False)

    # Prefer colony-scoped subscription when a colony is loaded so
    # filter_colony does the isolation work for us.
    runtime = colony_runtime if colony_runtime is not None else session.colony_runtime
    if runtime is not None:
        try:
            return runtime.subscribe_to_events(
                [EventType.ESCALATION_REQUESTED],
                _on_worker_escalation,
                filter_colony=runtime.colony_id,
            )
        except Exception:
            logger.warning("Failed to install colony-scoped escalation sub", exc_info=True)
            # fall through to session bus
    if session.event_bus is None:
        return None
    return session.event_bus.subscribe(
        event_types=[EventType.ESCALATION_REQUESTED],
        handler=_on_worker_escalation,
    )


# Cache TTL for the ambient credentials block. The block is rebuilt at most
# once per this interval; routes_credentials.invalidate_credentials_cache()
# forces an immediate rebuild on save/delete.
_CREDENTIALS_BLOCK_TTL_SECONDS = 30.0


def _build_credentials_provider() -> Any:
    """Return a closure that renders the ambient credentials block.

    The closure snapshots connected accounts via CredentialStoreAdapter and
    feeds them to build_accounts_prompt(). Output is connectivity-only —
    provider, alias, identity. No status / valid / expires_at fields, since
    those mislead the Queen the moment they go stale (liveness is enforced
    at tool-call time via CredentialExpiredError instead).
    """
    import time

    state: dict[str, Any] = {"cached": "", "cached_at": 0.0}

    def _provider() -> str:
        now = time.monotonic()
        if state["cached"] and (now - state["cached_at"]) < _CREDENTIALS_BLOCK_TTL_SECONDS:
            return state["cached"]

        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter

            from framework.orchestrator.prompting import build_accounts_prompt

            adapter = CredentialStoreAdapter.default()
            accounts = adapter.get_all_account_info()
            # Compact form (no tool_provider_map) — tool schemas already
            # surface function names; baking the full per-provider list
            # into the system prompt on every turn was ~2 KB of redundancy.
            rendered = build_accounts_prompt(accounts)
        except Exception:
            logger.debug("Failed to render ambient credentials block", exc_info=True)
            rendered = ""

        state["cached"] = rendered
        state["cached_at"] = now
        return rendered

    def _invalidate() -> None:
        state["cached_at"] = 0.0

    _provider.invalidate = _invalidate  # type: ignore[attr-defined]
    return _provider


def initialize_memory_scopes(session: Session, phase_state: Any) -> tuple[Path, Path]:
    """Create and cache the global and queen-scoped memory directories."""
    from framework.agents.queen.queen_memory_v2 import (
        global_memory_dir,
        init_memory_dir,
        queen_memory_dir,
    )

    global_dir = global_memory_dir()
    queen_dir = queen_memory_dir(session.queen_name)
    init_memory_dir(global_dir)
    init_memory_dir(queen_dir)
    phase_state.global_memory_dir = global_dir
    phase_state.queen_memory_dir = queen_dir
    return global_dir, queen_dir


async def materialize_queen_identity(
    session: Session,
    phase_state: Any,
    queen_profile: dict,
    event_bus: Any,
) -> None:
    """Format the queen identity prompt and set phase state.

    Called after SessionManager has resolved and loaded the profile.
    This function does no I/O — it only formats and caches.
    """
    from framework.agents.queen.queen_profiles import format_queen_identity_prompt
    from framework.host.event_bus import AgentEvent, EventType

    queen_id = session.queen_name

    phase_state.queen_id = queen_id
    phase_state.queen_profile = queen_profile
    phase_state.queen_identity_prompt = format_queen_identity_prompt(queen_profile, max_examples=1)

    if event_bus is not None:
        await event_bus.publish(
            AgentEvent(
                type=EventType.QUEEN_IDENTITY_SELECTED,
                stream_id="queen",
                data={
                    "queen_id": queen_id,
                    "name": queen_profile.get("name", ""),
                    "title": queen_profile.get("title", ""),
                },
            )
        )


def build_queen_tool_registry_bare() -> tuple[Any, dict[str, list[dict[str, Any]]]]:
    """Build a Queen ``ToolRegistry`` and a (server_name → tools) catalog.

    Used by the Tool Library GET route to populate the MCP tool surface
    without needing a live queen session. We DO NOT register queen
    lifecycle tools here (they require a Session stub); the catalog only
    covers MCP-origin tools, which is what the allowlist gates.

    Loading MCP servers spawns subprocesses, so call this once per
    backend process and cache the result.
    """
    from pathlib import Path

    import framework.agents.queen as _queen_pkg
    from framework.loader.mcp_registry import MCPRegistry
    from framework.loader.tool_registry import ToolRegistry

    queen_registry = ToolRegistry()
    queen_pkg_dir = Path(_queen_pkg.__file__).parent

    mcp_config = queen_pkg_dir / "mcp_servers.json"
    if mcp_config.exists():
        try:
            queen_registry.load_mcp_config(mcp_config)
        except Exception:
            logger.warning("build_queen_tool_registry_bare: MCP config failed", exc_info=True)

    try:
        reg = MCPRegistry()
        reg.initialize()
        if (queen_pkg_dir / "mcp_registry.json").is_file():
            queen_registry.set_mcp_registry_agent_path(queen_pkg_dir)
        registry_configs, selection_max_tools = reg.load_agent_selection(queen_pkg_dir)

        already = {cfg.get("name") for cfg in registry_configs if cfg.get("name")}
        extra: list[str] = []
        try:
            for entry in reg.list_installed():
                if entry.get("source") != "local":
                    continue
                if not entry.get("enabled", True):
                    continue
                name = entry.get("name")
                if name and name not in already:
                    extra.append(name)
        except Exception:
            pass
        if extra:
            try:
                extra_configs = reg.resolve_for_agent(include=extra)
                registry_configs = list(registry_configs) + [reg._server_config_to_dict(c) for c in extra_configs]
            except Exception:
                logger.debug("build_queen_tool_registry_bare: resolve_for_agent(extra) failed", exc_info=True)

        if registry_configs:
            queen_registry.load_registry_servers(
                registry_configs,
                preserve_existing_tools=True,
                log_collisions=False,
                max_tools=selection_max_tools,
            )
    except Exception:
        logger.warning("build_queen_tool_registry_bare: MCP registry load failed", exc_info=True)

    # Build the catalog.
    tools_by_name = queen_registry.get_tools()
    server_map = dict(getattr(queen_registry, "_mcp_server_tools", {}) or {})
    catalog: dict[str, list[dict[str, Any]]] = {}
    for server_name in sorted(server_map):
        entries: list[dict[str, Any]] = []
        for tool_name in sorted(server_map[server_name]):
            tool = tools_by_name.get(tool_name)
            if tool is None:
                continue
            entries.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
            )
        catalog[server_name] = entries

    return queen_registry, catalog


async def create_queen(
    session: Session,
    session_manager: Any,
    worker_identity: str | None,
    queen_dir: Path,
    queen_profile: dict,
    initial_prompt: str | None = None,
    initial_phase: str | None = None,
    tool_registry: ToolRegistry | None = None,
) -> asyncio.Task:
    """Build the queen executor and return the running asyncio task.

    Handles tool registration, phase-state initialization, prompt
    composition, queen identity materialization, colony preparation, and the queen
    event loop.
    """
    from framework.agents.queen.agent import (
        queen_goal,
        queen_loop_config as _base_loop_config,
    )
    from framework.agents.queen.nodes import (
        _QUEEN_INCUBATING_TOOLS,
        _QUEEN_INDEPENDENT_TOOLS,
        _QUEEN_REVIEWING_TOOLS,
        _QUEEN_WORKING_TOOLS,
        _queen_behavior_always,
        _queen_behavior_independent,
        _queen_character_core,
        _queen_role_incubating,
        _queen_role_independent,
        _queen_role_reviewing,
        _queen_role_working,
        _queen_style,
        _queen_tools_incubating,
        _queen_tools_independent,
        _queen_tools_reviewing,
        _queen_tools_working,
        finalize_queen_prompt,
    )
    from framework.host.event_bus import AgentEvent, EventType
    from framework.llm.capabilities import supports_image_tool_results
    from framework.loader.mcp_registry import MCPRegistry
    from framework.loader.tool_registry import ToolRegistry
    from framework.tools.queen_lifecycle_tools import (
        QueenPhaseState,
        register_queen_lifecycle_tools,
    )

    # ---- Tool registry ------------------------------------------------
    # Use pre-loaded cached registry if available (fast path)
    if tool_registry is not None:
        queen_registry = tool_registry
        logger.info("Queen: using pre-loaded tool registry with %d tools", len(queen_registry.get_tools()))
    else:
        # Build fresh (slow path - for backwards compatibility)
        queen_registry = ToolRegistry()
        import framework.agents.queen as _queen_pkg

        queen_pkg_dir = Path(_queen_pkg.__file__).parent
        mcp_config = queen_pkg_dir / "mcp_servers.json"
        if mcp_config.exists():
            try:
                queen_registry.load_mcp_config(mcp_config)
                logger.info("Queen: loaded MCP tools from %s", mcp_config)
            except Exception:
                logger.warning("Queen: MCP config failed to load", exc_info=True)

        try:
            registry = MCPRegistry()
            registry.initialize()
            if (queen_pkg_dir / "mcp_registry.json").is_file():
                queen_registry.set_mcp_registry_agent_path(queen_pkg_dir)
            registry_configs, selection_max_tools = registry.load_agent_selection(queen_pkg_dir)

            # Auto-include every user-added local MCP server that the repo
            # selection hasn't already loaded. Users register servers via
            # the `/api/mcp/servers` route (or `hive mcp add`); they live in
            # ~/.hive/mcp_registry/installed.json with source == "local".
            # New servers take effect on the next queen session start; the
            # prompt cache and ToolRegistry are still loaded once per boot.
            already_loaded_names = {cfg.get("name") for cfg in registry_configs if cfg.get("name")}
            extra_names: list[str] = []
            try:
                for entry in registry.list_installed():
                    if entry.get("source") != "local":
                        continue
                    if not entry.get("enabled", True):
                        continue
                    name = entry.get("name")
                    if not name or name in already_loaded_names:
                        continue
                    extra_names.append(name)
            except Exception:
                logger.debug("Queen: list_installed() failed while auto-including user servers", exc_info=True)

            if extra_names:
                try:
                    extra_configs = registry.resolve_for_agent(include=extra_names)
                    extra_dicts = [registry._server_config_to_dict(c) for c in extra_configs]
                    registry_configs = list(registry_configs) + extra_dicts
                    logger.info(
                        "Queen: auto-including %d user-added MCP server(s): %s",
                        len(extra_dicts),
                        [c.get("name") for c in extra_dicts],
                    )
                except Exception:
                    logger.warning(
                        "Queen: failed to resolve user-added MCP servers %s",
                        extra_names,
                        exc_info=True,
                    )

            if registry_configs:
                results = queen_registry.load_registry_servers(
                    registry_configs,
                    preserve_existing_tools=True,
                    log_collisions=True,
                    max_tools=selection_max_tools,
                )
                logger.info("Queen: loaded MCP registry servers: %s", results)
        except Exception:
            logger.warning("Queen: MCP registry config failed to load", exc_info=True)

    # ---- Phase state --------------------------------------------------
    # 3-phase model: caller supplies the phase directly (DM → independent,
    # colony bootstrap → working). Fall back to independent when nothing
    # is specified — there is no "staging"/"planning" bootstrap anymore.
    effective_phase = initial_phase or ("working" if worker_identity else "independent")
    phase_state = QueenPhaseState(phase=effective_phase, event_bus=session.event_bus)
    session.phase_state = phase_state

    # ---- Ambient credentials provider --------------------------------
    # Renders the "Connected integrations" block injected into every Queen
    # phase prompt so the Queen always knows which credentials are connected
    # without having to call list_credentials. Cached briefly to keep the
    # per-iteration prompt rebuild cheap; invalidated by routes_credentials
    # when the user adds/removes an integration.
    phase_state.credentials_prompt_provider = _build_credentials_provider()

    # ---- Lifecycle tools (always registered) --------------------------
    register_queen_lifecycle_tools(
        queen_registry,
        session=session,
        session_id=session.id,
        session_manager=session_manager,
        manager_session_id=session.id,
        phase_state=phase_state,
    )

    # ---- Colony runtime check (only when worker is loaded) ----------------
    if session.colony_runtime:
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        register_worker_monitoring_tools(
            queen_registry,
            session.worker_path,
            worker_graph_id=getattr(session.colony_runtime, "_graph_id", None)
            or getattr(session.colony_runtime, "graph", None)
            and session.colony_runtime.graph.id,
            default_session_id=session.id,
        )

    queen_tools = list(queen_registry.get_tools().values())
    queen_tool_executor = queen_registry.get_executor()

    # Phase 2 wiring: stash the resolved tool list + executor on the
    # session so SessionManager._start_queen can build a real
    # ColonyRuntime sharing the queen's tools, llm, and event bus.
    # The unified runtime is what run_parallel_workers (Phase 4) will
    # call into to fan out parallel workers from the queen.
    session._queen_tools = queen_tools  # type: ignore[attr-defined]
    session._queen_tool_executor = queen_tool_executor  # type: ignore[attr-defined]

    # ---- Partition tools by phase ------------------------------------
    independent_names = set(_QUEEN_INDEPENDENT_TOOLS)
    incubating_names = set(_QUEEN_INCUBATING_TOOLS)
    working_names = set(_QUEEN_WORKING_TOOLS)
    reviewing_names = set(_QUEEN_REVIEWING_TOOLS)

    registered_names = {t.name for t in queen_tools}
    logger.info("Queen: registered tools: %s", sorted(registered_names))

    phase_state.working_tools = [t for t in queen_tools if t.name in working_names]
    phase_state.reviewing_tools = [t for t in queen_tools if t.name in reviewing_names]
    # Incubating tool surface is intentionally minimal (read-only inspection
    # + create_colony + cancel_incubation) — no MCP tools spliced in, so the
    # queen stays focused on drafting the spec.
    phase_state.incubating_tools = [t for t in queen_tools if t.name in incubating_names]

    # Independent phase gets core tools + all MCP tools not claimed by any
    # other phase (coder-tools file I/O, gcu-tools browser, etc.).
    all_phase_names = independent_names | incubating_names | working_names | reviewing_names
    mcp_tools = [t for t in queen_tools if t.name not in all_phase_names]
    phase_state.independent_tools = [t for t in queen_tools if t.name in independent_names] + mcp_tools
    logger.info(
        "Queen: independent tools: %s",
        sorted(t.name for t in phase_state.independent_tools),
    )
    logger.info(
        "Queen: incubating tools: %s",
        sorted(t.name for t in phase_state.incubating_tools),
    )

    # ---- Per-queen MCP tool allowlist --------------------------------
    # Capture the set of MCP-origin tool names so the allowlist in
    # ``QueenPhaseState`` only gates MCP tools (lifecycle and synthetic
    # tools always pass through). Then apply the queen profile's stored
    # allowlist (if any) and memoize the filtered independent tool list.
    mcp_server_tools_map: dict[str, set[str]] = dict(getattr(queen_registry, "_mcp_server_tools", {}))
    phase_state.mcp_tool_names_all = set().union(*mcp_server_tools_map.values()) if mcp_server_tools_map else set()
    # The queen's MCP tool allowlist now lives in a dedicated
    # ``tools.json`` sidecar next to ``profile.yaml``. ``load_queen_tools_config``
    # migrates any legacy ``enabled_mcp_tools`` field out of profile.yaml
    # on first read, so existing installs upgrade silently.
    from framework.agents.queen.queen_tools_config import load_queen_tools_config

    # Build a minimal catalog for default-tool resolution. The full
    # ``session_manager._mcp_tool_catalog`` snapshot is written further
    # down the flow; a queen booted for the first time needs the catalog
    # now so ``@server:NAME`` shorthands in the role-default table can
    # expand against the just-loaded MCP servers.
    _boot_catalog: dict[str, list[dict]] = {
        srv: [{"name": name} for name in sorted(names)] for srv, names in mcp_server_tools_map.items()
    }
    # ``queen_dir`` is ``queens/<queen_id>/sessions/<session_id>``; the
    # allowlist sidecar is keyed by queen_id, not session_id.
    phase_state.enabled_mcp_tools = load_queen_tools_config(session.queen_name, _boot_catalog)
    phase_state.rebuild_independent_filter()
    if phase_state.enabled_mcp_tools is not None:
        total_mcp = len(phase_state.mcp_tool_names_all)
        allowed_mcp = len(set(phase_state.enabled_mcp_tools) & phase_state.mcp_tool_names_all)
        logger.info(
            "Queen: per-queen MCP allowlist active — %d of %d MCP tools enabled",
            allowed_mcp,
            total_mcp,
        )

    # ---- MCP tool catalog for the frontend ---------------------------
    # Snapshot per-server tool metadata so the Queen Tools API can render
    # the tool surface without spawning MCP subprocesses. Keyed by server
    # name so the UI can group tools by origin. Updated every time a
    # queen boots, so installing a new server and starting a new queen
    # session refreshes the catalog.
    mcp_tool_catalog: dict[str, list[dict[str, Any]]] = {}
    tools_by_name = {t.name: t for t in queen_tools}
    for server_name, tool_names in mcp_server_tools_map.items():
        server_entries: list[dict[str, Any]] = []
        for tool_name in sorted(tool_names):
            tool = tools_by_name.get(tool_name)
            if tool is None:
                continue
            server_entries.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
            )
        mcp_tool_catalog[server_name] = server_entries
    # All queens share one MCP registry, so the catalog is a manager-level
    # fact; stash it on the SessionManager so the Queen Tools route can
    # render the tool list even when no queen session is currently live.
    if session_manager is not None:
        try:
            session_manager._mcp_tool_catalog = mcp_tool_catalog  # type: ignore[attr-defined]
        except Exception:
            logger.debug("Queen: could not attach mcp_tool_catalog to manager", exc_info=True)

    # ---- Global + queen-scoped memory ----------------------------------
    global_dir, queen_mem_dir = initialize_memory_scopes(session, phase_state)

    # Materialize the selected queen identity before building the initial
    # system prompt so the first turn includes the profile's core identity.
    await materialize_queen_identity(
        session=session,
        phase_state=phase_state,
        queen_profile=queen_profile,
        event_bus=session.event_bus,
    )

    # ---- Compose phase-specific prompts ------------------------------
    from framework.agents.queen.nodes import queen_node as _orig_node

    # Resolve vision-only prompt sections based on the session's LLM.
    # session.llm is immutable for the session's lifetime, so this check
    # is stable — prompts never need to be recomposed mid-session.
    _has_vision = bool(session.llm and supports_image_tool_results(getattr(session.llm, "model", "")))

    phase_state.prompt_independent = finalize_queen_prompt(
        (
            _queen_character_core
            + _queen_role_independent
            + _queen_style
            + _queen_tools_independent
            + _queen_behavior_always
            + _queen_behavior_independent
        ),
        _has_vision,
    )
    phase_state.prompt_incubating = finalize_queen_prompt(
        (
            _queen_character_core
            + _queen_role_incubating
            + _queen_style
            + _queen_tools_incubating
            + _queen_behavior_always
        ),
        _has_vision,
    )
    phase_state.prompt_working = finalize_queen_prompt(
        (_queen_character_core + _queen_role_working + _queen_style + _queen_tools_working + _queen_behavior_always),
        _has_vision,
    )
    phase_state.prompt_reviewing = finalize_queen_prompt(
        (
            _queen_character_core
            + _queen_role_reviewing
            + _queen_style
            + _queen_tools_reviewing
            + _queen_behavior_always
        ),
        _has_vision,
    )

    # ---- Default skill protocols -------------------------------------
    _queen_skill_dirs: list[str] = []
    try:
        from framework.config import QUEENS_DIR
        from framework.skills.discovery import ExtraScope
        from framework.skills.manager import SkillsManager, SkillsManagerConfig

        # Queen home backs the queen-UI skill scope and the queen's
        # override store. The directory already exists (or is created on
        # demand by queen_profiles.py); treat a missing queen_name as the
        # default queen to preserve backwards compatibility.
        _queen_id = getattr(session, "queen_name", None) or "default"
        _queen_home = QUEENS_DIR / _queen_id
        _queen_skills_mgr = SkillsManager(
            SkillsManagerConfig(
                queen_id=_queen_id,
                queen_overrides_path=_queen_home / "skills_overrides.json",
                extra_scope_dirs=[
                    ExtraScope(
                        directory=_queen_home / "skills",
                        label="queen_ui",
                        priority=2,
                    )
                ],
                # No project_root — queen's project is her own identity;
                # user-scope discovery still runs without one.
                project_root=None,
                skip_community_discovery=True,
                interactive=False,
            )
        )
        _queen_skills_mgr.load()
        phase_state.protocols_prompt = _queen_skills_mgr.protocols_prompt
        phase_state.skills_catalog_prompt = _queen_skills_mgr.skills_catalog_prompt
        # Also store the manager so get_current_prompt() can render a
        # phase-filtered catalog on each turn (skills with a `visibility`
        # frontmatter that excludes the current phase are dropped).
        phase_state.skills_manager = _queen_skills_mgr
        _queen_skill_dirs = _queen_skills_mgr.allowlisted_dirs
    except Exception:
        logger.debug("Queen skill loading failed (non-fatal)", exc_info=True)

    # ---- Queen identity + recall -------------------------------------
    _session_llm = session.llm
    _session_event_bus = session.event_bus

    async def _refresh_recall_cache(query: str) -> None:
        """Populate the cached recall block for the next queen prompt."""
        if not query or not isinstance(query, str):
            return
        try:
            from framework.agents.queen.recall_selector import (
                build_scoped_recall_blocks,
            )

            global_block, queen_block = await build_scoped_recall_blocks(
                query,
                _session_llm,
                global_memory_dir=phase_state.global_memory_dir,
                queen_memory_dir=phase_state.queen_memory_dir,
                queen_id=phase_state.queen_id or session.queen_name,
            )
            phase_state._cached_global_recall_block = global_block
            phase_state._cached_queen_recall_block = queen_block
        except Exception:
            logger.debug("recall: cache update failed", exc_info=True)

    # ---- Recall on each real user turn --------------------------------
    async def _recall_on_user_input(event: AgentEvent) -> None:
        """On real user input, freeze the dynamic system-prompt suffix and
        refresh recall memories in the background.

        The EventBus drops handlers that exceed 15s, so we MUST return fast.
        Recall selection queries the LLM and can take >15s on slow backends;
        we fire it off as a background task and re-stamp the suffix when it
        completes. The immediate refresh_dynamic_suffix call stamps a fresh
        timestamp using the last-known recall blocks so every iteration of
        THIS user turn sees a byte-stable prompt (prompt cache hits on the
        static block). Phase-change injections and worker-report injections
        go through agent_loop.inject_event() and do NOT publish
        CLIENT_INPUT_RECEIVED, so this runs exactly once per real user turn.
        """
        query = (event.data or {}).get("content", "")
        # Immediate: stamp "now" into the frozen suffix, using whatever
        # recall blocks we already cached (from the prior turn or seeding).
        phase_state.refresh_dynamic_suffix()

        async def _bg_refresh() -> None:
            try:
                await _refresh_recall_cache(query)
                # Re-stamp with the fresh recall blocks. Any iteration that
                # read the suffix before this point used the older recall
                # — acceptable; recall was already eventual-consistency.
                phase_state.refresh_dynamic_suffix()
            except Exception:
                logger.debug("background recall refresh failed", exc_info=True)

        import asyncio as _asyncio

        _asyncio.create_task(_bg_refresh())

    session.event_bus.subscribe(
        [EventType.CLIENT_INPUT_RECEIVED],
        _recall_on_user_input,
        filter_stream="queen",
    )

    async def _queen_identity_hook(ctx: HookContext) -> HookResult | None:
        from framework.agent_loop.internals.types import HookResult
        from framework.agents.queen.queen_profiles import (
            ensure_default_queens,
            format_queen_identity_prompt,
            load_queen_profile,
            select_queen,
        )

        ensure_default_queens()
        trigger = ctx.trigger or ""
        # If the session was pre-bound to a queen (user clicked a specific
        # queen in the UI), use that identity instead of LLM auto-selection.
        # Also skip LLM auto-selection if queen was already selected during
        # session creation (e.g., from home screen classification).
        if session.queen_name and session.queen_name != "default":
            queen_id = session.queen_name
            logger.info("Using pre-selected queen: %s", queen_id)
        else:
            # This should rarely happen now - queen is selected at session creation
            logger.warning("No pre-selected queen, falling back to LLM classification")
            queen_id = await select_queen(trigger, _session_llm)
        try:
            profile = load_queen_profile(queen_id)
        except FileNotFoundError:
            logger.warning("Queen profile %s not found after selection", queen_id)
            return None
        identity_prompt = format_queen_identity_prompt(profile, max_examples=1)
        # Store on phase_state so identity persists across dynamic prompt refreshes
        phase_state.queen_id = queen_id
        phase_state.queen_profile = profile
        phase_state.queen_identity_prompt = identity_prompt
        # Route session storage to ~/.hive/agents/queens/{queen_id}/sessions/
        session.queen_name = queen_id

        # Relocate session dir from default/ to the selected queen's dir
        # so all writes (conversations, events) go to the correct queen.
        if queen_id != "default" and session.queen_dir:
            import json as _json
            import shutil as _shutil

            _old_dir = session.queen_dir
            if _old_dir.exists() and _old_dir.parent.parent.name == "default":
                from framework.config import QUEENS_DIR as _QD

                _new_dir = _QD / queen_id / "sessions" / _old_dir.name
                _new_dir.parent.mkdir(parents=True, exist_ok=True)
                _shutil.move(str(_old_dir), str(_new_dir))
                session.queen_dir = _new_dir
                logger.info(
                    "Relocated queen session dir: %s -> %s",
                    _old_dir,
                    _new_dir,
                )
                # Update meta.json queen_id
                _meta_path = _new_dir / "meta.json"
                if _meta_path.exists():
                    try:
                        _meta = _json.loads(_meta_path.read_text(encoding="utf-8"))
                        _meta["queen_id"] = queen_id
                        _meta_path.write_text(_json.dumps(_meta, ensure_ascii=False), encoding="utf-8")
                    except (OSError, _json.JSONDecodeError):
                        pass
                # Re-point event bus log to new location, preserving offset
                _offset = getattr(session.event_bus, "_session_log_iteration_offset", 0)
                session.event_bus.set_session_log(_new_dir / "events.jsonl", iteration_offset=_offset)

        if _session_event_bus is not None:
            await _session_event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_IDENTITY_SELECTED,
                    stream_id="queen",
                    data={
                        "queen_id": queen_id,
                        "name": profile.get("name", ""),
                        "title": profile.get("title", ""),
                    },
                )
            )

        # Seed recall cache so the first turn has relevant memories.
        # Use a short timeout to avoid blocking the first turn on slow models.
        if trigger:
            try:
                import asyncio

                from framework.agents.queen.recall_selector import (
                    format_recall_injection,
                    select_memories,
                )

                mem_dir = phase_state.global_memory_dir
                selected = await asyncio.wait_for(
                    select_memories(trigger, _session_llm, mem_dir),
                    timeout=3.0,
                )
                phase_state._cached_global_recall_block = format_recall_injection(selected, mem_dir)
            except TimeoutError:
                logger.debug("recall: initial seeding timed out, will retry on first turn")
            except Exception:
                logger.debug("recall: initial seeding failed", exc_info=True)

        # Freeze the dynamic suffix once so the first real turn sends a
        # byte-stable prompt even before CLIENT_INPUT_RECEIVED fires.
        phase_state.refresh_dynamic_suffix()
        return HookResult(system_prompt=phase_state.get_current_prompt())

    # ---- Colony preparation -------------------------------------------
    initial_prompt_text = phase_state.get_current_prompt()

    registered_tool_names = set(queen_registry.get_tools().keys())
    declared_tools = _orig_node.tools or []
    available_tools = [t for t in declared_tools if t in registered_tool_names]

    node_updates: dict = {
        "system_prompt": initial_prompt_text,
    }
    if set(available_tools) != set(declared_tools):
        missing = sorted(set(declared_tools) - registered_tool_names)
        if missing:
            logger.debug("Queen: tools not yet available (registered on worker load): %s", missing)
        node_updates["tools"] = available_tools

    _orig_node.model_copy(update=node_updates)

    # Determine session mode:
    # - RESTORE: Resume cold session with history, no initial prompt -> wait for user
    # - FRESH:   New session OR explicit initial prompt -> greet immediately
    _is_restore_mode = bool(session.queen_resume_from) and initial_prompt is None

    _queen_loop_config = {**_base_loop_config}

    # ---- Queen event loop (AgentLoop directly, no Orchestrator) -------
    from types import SimpleNamespace

    from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
    from framework.agent_loop.types import AgentContext, AgentSpec
    from framework.storage.conversation_store import FileConversationStore

    async def _queen_loop():
        logger.debug("[_queen_loop] Starting queen loop for session %s", session.id)
        # Scope the browser profile to this session so parallel queens each
        # drive their own Chrome tab group instead of fighting over "default".
        # Browser tools run in a stdio MCP subprocess, so we can't set a
        # contextvar across processes — instead we inject `profile` as a
        # CONTEXT_PARAM that ToolRegistry passes into every MCP call. The
        # token stays local to this task.
        try:
            from framework.loader.tool_registry import ToolRegistry

            ToolRegistry.set_execution_context(profile=session.id)
        except Exception:
            logger.debug("Queen: failed to set browser profile for session %s", session.id, exc_info=True)
        try:
            lc = _queen_loop_config
            queen_loop_config = LoopConfig(
                max_iterations=lc.get("max_iterations", 999_999),
                max_tool_calls_per_turn=lc.get("max_tool_calls_per_turn", 30),
                max_context_tokens=lc.get("max_context_tokens", 180_000),
                max_tool_result_chars=lc.get("max_tool_result_chars", 30_000),
                spillover_dir=str(queen_dir / "data"),
                hooks=lc.get("hooks", {}),
            )

            conversation_store = FileConversationStore(queen_dir / "conversations")

            agent_loop = AgentLoop(
                event_bus=session.event_bus,
                config=queen_loop_config,
                tool_executor=queen_tool_executor,
                conversation_store=conversation_store,
            )

            from framework.tracker.decision_tracker import DecisionTracker

            queen_spec = AgentSpec(
                id="queen",
                name="Queen",
                description="Queen agent — manages the colony and interacts with the user.",
                system_prompt="",
                tools=[t.name for t in queen_tools],
                tool_access_policy="all",
                # Queen is a forever-alive conversational agent: bypass
                # the implicit judge entirely. Without this, a text-only
                # turn (greeting, clarifying question, summary) falls
                # through to the default ACCEPT verdict in
                # judge_pipeline.py, which terminates the loop and
                # leaves session.queen_executor=None until the user
                # reloads. Mirrors the static queen_node NodeSpec in
                # framework.agents.queen.nodes which already sets this.
                skip_judge=True,
            )

            ctx = AgentContext(
                runtime=DecisionTracker(queen_dir),
                agent_id="queen",
                agent_spec=queen_spec,
                llm=session.llm,
                available_tools=queen_tools,
                goal_context=queen_goal.to_prompt_context(),
                max_tokens=lc.get("max_tokens", 8192),
                stream_id="queen",
                execution_id=session.id,
                dynamic_tools_provider=phase_state.get_current_tools,
                dynamic_prompt_provider=phase_state.get_static_prompt,
                dynamic_prompt_suffix_provider=phase_state.get_dynamic_suffix,
                iteration_metadata_provider=lambda: {"phase": phase_state.phase},
                skills_catalog_prompt=phase_state.skills_catalog_prompt,
                protocols_prompt=phase_state.protocols_prompt,
                skill_dirs=_queen_skill_dirs,
            )

            session.queen_executor = SimpleNamespace(
                node_registry={"queen": agent_loop},
            )

            async def _inject_phase_notification(content: str) -> None:
                await agent_loop.inject_event(content)

            phase_state.inject_notification = _inject_phase_notification

            async def _on_worker_report(event):
                """Inject [WORKER_REPORT] into queen as each worker finishes.

                Subscribes to SUBAGENT_REPORT events which carry the worker's
                real summary/data (preferring any explicit ``report_to_parent``
                call). Every spawned worker emits exactly one — success,
                partial, failed, timeout, or stopped. The queen sees the
                report as the next user turn and can react (reply to user,
                kick off follow-up work, etc.) without being blocked by the
                spawn call itself.
                """
                if event.stream_id == "queen":
                    return
                data = event.data or {}
                worker_id = data.get("worker_id", event.node_id or "unknown")
                status = data.get("status", "unknown")
                summary = data.get("summary") or "(no summary)"
                err = data.get("error")
                payload_data = data.get("data") or {}
                duration = data.get("duration_seconds")

                lines = ["[WORKER_REPORT]", f"worker_id: {worker_id}", f"status: {status}"]
                if duration is not None:
                    try:
                        lines.append(f"duration: {float(duration):.1f}s")
                    except (TypeError, ValueError):
                        pass
                lines.append(f"summary: {summary}")
                if err:
                    lines.append(f"error: {err}")
                if payload_data:
                    # Compact JSON so the queen sees all keys without the
                    # indentation blowing up the turn's token count.
                    try:
                        import json as _json

                        lines.append("data: " + _json.dumps(payload_data, ensure_ascii=False, default=str))
                    except Exception:
                        lines.append(f"data: {payload_data!r}")
                notification = "\n".join(lines)

                await agent_loop.inject_event(notification)
                session.worker_configured = True

                # Only transition to reviewing once the batch has quieted —
                # if other workers from a parallel spawn are still live, stay
                # in working so the queen's tool access (run_parallel_workers,
                # inject_message, stop_worker) remains available.
                colony_runtime = getattr(session, "colony_runtime", None)
                still_active = 0
                if colony_runtime is not None:
                    try:
                        still_active = sum(
                            1
                            for w in colony_runtime._workers.values()  # type: ignore[attr-defined]
                            if getattr(w, "is_active", False)
                        )
                    except Exception:
                        still_active = 0
                if still_active == 0 and phase_state.phase in ("working", "running"):
                    await phase_state.switch_to_reviewing(source="auto")

            session.event_bus.subscribe(
                event_types=[EventType.SUBAGENT_REPORT],
                handler=_on_worker_report,
            )

            # ---- Colony-scoped worker escalation routing ----
            # Replaces the legacy unfiltered SessionManager subscription.
            # ``filter_colony`` (inside install_worker_escalation_routing)
            # ensures only escalations from workers in THIS queen's colony
            # reach THIS queen — cross-colony leakage is structurally
            # impossible because StreamEventBus stamps colony_id on every
            # published event before dispatch.
            session.worker_handoff_sub = install_worker_escalation_routing(session)

            from framework.agents.queen.reflection_agent import subscribe_reflection_triggers

            _reflection_subs = await subscribe_reflection_triggers(
                session.event_bus,
                queen_dir,
                session.llm,
                global_memory_dir=global_dir,
                queen_memory_dir=queen_mem_dir,
                queen_id=session.queen_name,
            )
            session.memory_reflection_subs = _reflection_subs

            # Set initial user message based on mode:
            # - RESTORE:              None -> AgentLoop restores from disk, waits for /chat
            # - FRESH + initial_prompt:     -> queen responds to the real prompt immediately
            # - FRESH + no initial_prompt:  -> None -> AgentLoop waits for the first /chat
            #
            # The third case matters for the classify→createNewSession→chat
            # bootstrap: if the frontend doesn't pass initial_prompt, we must
            # NOT invent a phantom "Hello" — that used to concatenate with the
            # real first chat message and confuse the model.
            ctx.input_data = {"user_request": None if _is_restore_mode else (initial_prompt or None)}

            # Publish the initial prompt as a CLIENT_INPUT_RECEIVED event so
            # it appears in the SSE stream and persists to events.jsonl for
            # session resume.  The /chat endpoint does the same for injected
            # messages; this covers the session-creation-with-prompt path.
            if initial_prompt and not _is_restore_mode:
                await session.event_bus.publish(
                    AgentEvent(
                        type=EventType.CLIENT_INPUT_RECEIVED,
                        stream_id="queen",
                        node_id="queen",
                        execution_id=session.id,
                        data={"content": initial_prompt},
                    )
                )

            logger.info(
                "Queen %s in %s phase with %d tools: %s",
                "restoring" if _is_restore_mode else "starting",
                phase_state.phase,
                len(phase_state.get_current_tools()),
                [t.name for t in phase_state.get_current_tools()],
            )

            # Run the queen -- forever-alive conversation loop
            result = await agent_loop.execute(ctx)

            # AgentResult doesn't have stop_reason — check success/error.
            # The queen is expected to be forever-alive; a clean return
            # means the loop hit max_iterations or decided to exit.
            if result.success:
                logger.warning("Queen returned (should be forever-alive)")
            elif result.error:
                logger.error("Queen failed: %s", result.error)

        except asyncio.CancelledError:
            logger.info("[_queen_loop] Queen loop cancelled (normal shutdown)")
            raise
        except Exception as e:
            logger.exception("[_queen_loop] Queen conversation crashed: %s", e)
            raise
        finally:
            logger.warning(
                "[_queen_loop] Queen loop exiting — clearing queen_executor for session '%s'",
                session.id,
            )
            session.queen_executor = None

    return asyncio.create_task(_queen_loop())
