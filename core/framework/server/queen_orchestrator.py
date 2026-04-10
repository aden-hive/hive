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
        worker_id = stream_id[len("worker:"):]
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
                        "[QUEEN_REPLY] queue_full — queen inbox saturated; "
                        "proceed with best judgment or retry later.",
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
                "Use reply_to_worker(request_id, reply) to unblock, "
                "or list_worker_questions() to see all pending."
            )
        else:
            lines.append(
                "No request_id — use inject_message(content=...) to relay "
                "guidance manually."
            )
        handoff = "\n".join(lines)

        # Fallback: if the queen loop has gone away, publish a
        # CLIENT_INPUT_REQUESTED so the human sees the question and the
        # worker does not wedge.
        queen_node = (
            session.queen_executor.node_registry.get("queen")
            if session.queen_executor is not None
            else None
        )
        if queen_node is None or not hasattr(queen_node, "inject_event"):
            if session.event_bus is not None:
                await session.event_bus.emit_client_input_requested(
                    stream_id="queen",
                    node_id="queen",
                    prompt=handoff,
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
            logger.warning(
                "Failed to install colony-scoped escalation sub", exc_info=True
            )
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
        if (
            state["cached"]
            and (now - state["cached_at"]) < _CREDENTIALS_BLOCK_TTL_SECONDS
        ):
            return state["cached"]

        try:
            from aden_tools.credentials.store_adapter import CredentialStoreAdapter
            from framework.orchestrator.prompting import build_accounts_prompt

            adapter = CredentialStoreAdapter.default()
            accounts = adapter.get_all_account_info()
            tool_provider_map = adapter.get_tool_provider_map()
            rendered = build_accounts_prompt(
                accounts,
                tool_provider_map=tool_provider_map,
                node_tool_names=None,
            )
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


async def create_queen(
    session: Session,
    session_manager: Any,
    worker_identity: str | None,
    queen_dir: Path,
    initial_prompt: str | None = None,
    initial_phase: str | None = None,
) -> asyncio.Task:
    """Build the queen executor and return the running asyncio task.

    Handles tool registration, phase-state initialization, prompt
    composition, persona hook setup, colony preparation, and the queen
    event loop.
    """
    from framework.agents.queen.agent import (
        queen_goal,
        queen_loop_config as _base_loop_config,
    )
    from framework.agents.queen.nodes import (
        _QUEEN_BUILDING_TOOLS,
        _QUEEN_EDITING_TOOLS,
        _QUEEN_INDEPENDENT_TOOLS,
        _QUEEN_PLANNING_TOOLS,
        _QUEEN_RUNNING_TOOLS,
        _QUEEN_STAGING_TOOLS,
        _appendices,
        _building_knowledge,
        _planning_knowledge,
        _queen_behavior_always,
        _queen_behavior_building,
        _queen_behavior_editing,
        _queen_behavior_independent,
        _queen_behavior_planning,
        _queen_behavior_running,
        _queen_behavior_staging,
        _queen_character_core,
        _queen_identity_editing,
        _queen_phase_7,
        _queen_role_building,
        _queen_role_independent,
        _queen_role_planning,
        _queen_role_running,
        _queen_role_staging,
        _queen_style,
        _queen_tools_building,
        _queen_tools_editing,
        _queen_tools_independent,
        _queen_tools_planning,
        _queen_tools_running,
        _queen_tools_staging,
        _shared_building_knowledge,
    )
    from framework.agents.queen.queen_profiles import (
        ensure_default_queens,
        format_queen_identity_prompt,
        load_queen_profile,
        select_queen,
    )
    from framework.agent_loop.agent_loop import HookContext, HookResult
    from framework.loader.mcp_registry import MCPRegistry
    from framework.loader.tool_registry import ToolRegistry
    from framework.host.event_bus import AgentEvent, EventType
    from framework.tools.queen_lifecycle_tools import (
        QueenPhaseState,
        register_queen_lifecycle_tools,
    )

    # ---- Tool registry ------------------------------------------------
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
    effective_phase = initial_phase or ("staging" if worker_identity else "planning")
    phase_state = QueenPhaseState(phase=effective_phase, event_bus=session.event_bus)
    session.phase_state = phase_state

    # ---- Ambient credentials provider --------------------------------
    # Renders the "Connected integrations" block injected into every Queen
    # phase prompt so the Queen always knows which credentials are connected
    # without having to call list_credentials. Cached briefly to keep the
    # per-iteration prompt rebuild cheap; invalidated by routes_credentials
    # when the user adds/removes an integration.
    phase_state.credentials_prompt_provider = _build_credentials_provider()

    # ---- Track ask rounds during planning ----------------------------
    # Increment planning_ask_rounds each time the queen requests user
    # input (ask_user or ask_user_multiple) while in the planning phase.
    async def _track_planning_asks(event: AgentEvent) -> None:
        if phase_state.phase != "planning":
            return
        # Only count explicit ask_user / ask_user_multiple calls, not
        # auto-block (text-only turns emit CLIENT_INPUT_REQUESTED with
        # an empty prompt and no options/questions).
        data = event.data or {}
        has_prompt = bool(data.get("prompt"))
        has_questions = bool(data.get("questions"))
        has_options = bool(data.get("options"))
        if has_prompt or has_questions or has_options:
            phase_state.planning_ask_rounds += 1

    session.event_bus.subscribe(
        [EventType.CLIENT_INPUT_REQUESTED],
        _track_planning_asks,
        filter_stream="queen",
    )

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
    planning_names = set(_QUEEN_PLANNING_TOOLS)
    building_names = set(_QUEEN_BUILDING_TOOLS)
    staging_names = set(_QUEEN_STAGING_TOOLS)
    running_names = set(_QUEEN_RUNNING_TOOLS)
    editing_names = set(_QUEEN_EDITING_TOOLS)
    independent_names = set(_QUEEN_INDEPENDENT_TOOLS)

    registered_names = {t.name for t in queen_tools}
    missing_building = building_names - registered_names
    if missing_building:
        logger.warning(
            "Queen: %d/%d building tools NOT registered: %s",
            len(missing_building),
            len(building_names),
            sorted(missing_building),
        )
    logger.info("Queen: registered tools: %s", sorted(registered_names))

    phase_state.planning_tools = [t for t in queen_tools if t.name in planning_names]
    phase_state.building_tools = [t for t in queen_tools if t.name in building_names]
    phase_state.staging_tools = [t for t in queen_tools if t.name in staging_names]
    phase_state.running_tools = [t for t in queen_tools if t.name in running_names]
    phase_state.editing_tools = [t for t in queen_tools if t.name in editing_names]

    # Independent phase gets core tools + all MCP tools not claimed by any
    # other phase (coder-tools file I/O, gcu-tools browser, etc.).
    all_phase_names = (
        planning_names | building_names | staging_names | running_names | editing_names
    )
    mcp_tools = [t for t in queen_tools if t.name not in all_phase_names]
    phase_state.independent_tools = [
        t for t in queen_tools if t.name in independent_names
    ] + mcp_tools
    logger.info(
        "Queen: independent tools: %s",
        sorted(t.name for t in phase_state.independent_tools),
    )

    # ---- Global memory -------------------------------------------------
    from framework.agents.queen.queen_memory_v2 import (
        global_memory_dir,
        init_memory_dir,
    )

    global_dir = global_memory_dir()
    init_memory_dir(global_dir)
    phase_state.global_memory_dir = global_dir

    # ---- Compose phase-specific prompts ------------------------------
    from framework.agents.queen.nodes import queen_node as _orig_node

    if worker_identity is None:
        worker_identity = (
            "\n\n# Worker Profile\n"
            "No worker agent loaded. You are operating independently.\n"
            "Design or build the agent to solve the user's problem "
            "according to your current phase."
        )

    _planning_body = (
        _queen_character_core
        + _queen_role_planning
        + _queen_style
        + _shared_building_knowledge
        + _queen_tools_planning
        + _queen_behavior_always
        + _queen_behavior_planning
        + _planning_knowledge
        + worker_identity
    )
    phase_state.prompt_planning = _planning_body

    _building_body = (
        _queen_character_core
        + _queen_role_building
        + _queen_style
        + _shared_building_knowledge
        + _queen_tools_building
        + _queen_behavior_always
        + _queen_behavior_building
        + _building_knowledge
        + _queen_phase_7
        + _appendices
        + worker_identity
    )
    phase_state.prompt_building = _building_body
    phase_state.prompt_staging = (
        _queen_character_core
        + _queen_role_staging
        + _queen_style
        + _queen_tools_staging
        + _queen_behavior_always
        + _queen_behavior_staging
        + worker_identity
    )
    phase_state.prompt_running = (
        _queen_character_core
        + _queen_role_running
        + _queen_style
        + _queen_tools_running
        + _queen_behavior_always
        + _queen_behavior_running
        + worker_identity
    )
    phase_state.prompt_editing = (
        _queen_identity_editing
        + _queen_style
        + _queen_tools_editing
        + _queen_behavior_always
        + _queen_behavior_editing
        + worker_identity
    )
    phase_state.prompt_independent = (
        _queen_character_core
        + _queen_role_independent
        + _queen_style
        + _queen_tools_independent
        + _queen_behavior_always
        + _queen_behavior_independent
    )

    # ---- Default skill protocols -------------------------------------
    _queen_skill_dirs: list[str] = []
    try:
        from framework.skills.manager import SkillsManager, SkillsManagerConfig

        # Pass project_root so user-scope skills (~/.hive/skills/, ~/.agents/skills/)
        # are discovered. Queen has no agent-specific project root, so we use its
        # own directory — the value just needs to be non-None to enable user-scope scanning.
        _queen_skills_mgr = SkillsManager(SkillsManagerConfig(project_root=Path(__file__).parent))
        _queen_skills_mgr.load()
        phase_state.protocols_prompt = _queen_skills_mgr.protocols_prompt
        phase_state.skills_catalog_prompt = _queen_skills_mgr.skills_catalog_prompt
        _queen_skill_dirs = _queen_skills_mgr.allowlisted_dirs
    except Exception:
        logger.debug("Queen skill loading failed (non-fatal)", exc_info=True)

    # ---- Queen identity hook -----------------------------------------
    _session_llm = session.llm
    _session_event_bus = session.event_bus

    # ---- Recall on each real user turn --------------------------------
    async def _recall_on_user_input(event: AgentEvent) -> None:
        """Re-select memories when real user input arrives."""
        content = (event.data or {}).get("content", "")
        if not content or not isinstance(content, str):
            return
        try:
            from framework.agents.queen.recall_selector import (
                format_recall_injection,
                select_memories,
            )

            mem_dir = phase_state.global_memory_dir
            selected = await select_memories(content, _session_llm, mem_dir)
            phase_state._cached_global_recall_block = format_recall_injection(selected, mem_dir)
        except Exception:
            logger.debug("recall: user-turn cache update failed", exc_info=True)

    session.event_bus.subscribe(
        [EventType.CLIENT_INPUT_RECEIVED],
        _recall_on_user_input,
        filter_stream="queen",
    )

    async def _queen_identity_hook(ctx: HookContext) -> HookResult | None:
        ensure_default_queens()
        trigger = ctx.trigger or ""
        # If the session was pre-bound to a queen (user clicked a specific
        # queen in the UI), use that identity instead of LLM auto-selection.
        if session.queen_name and session.queen_name != "default":
            queen_id = session.queen_name
        else:
            queen_id = await select_queen(trigger, _session_llm)
        try:
            profile = load_queen_profile(queen_id)
        except FileNotFoundError:
            logger.warning("Queen profile %s not found after selection", queen_id)
            return None
        identity_prompt = format_queen_identity_prompt(profile)
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
                        _meta_path.write_text(
                            _json.dumps(_meta, ensure_ascii=False), encoding="utf-8"
                        )
                    except (OSError, _json.JSONDecodeError):
                        pass
                # Re-point event bus log to new location, preserving offset
                _offset = getattr(
                    session.event_bus, "_session_log_iteration_offset", 0
                )
                session.event_bus.set_session_log(
                    _new_dir / "events.jsonl", iteration_offset=_offset
                )

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
        if trigger:
            try:
                from framework.agents.queen.recall_selector import (
                    format_recall_injection,
                    select_memories,
                )

                mem_dir = phase_state.global_memory_dir
                selected = await select_memories(trigger, _session_llm, mem_dir)
                phase_state._cached_global_recall_block = format_recall_injection(selected, mem_dir)
            except Exception:
                logger.debug("recall: initial seeding failed", exc_info=True)

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

    adjusted_node = _orig_node.model_copy(update=node_updates)

    # Determine session mode:
    # - RESTORE: Resume cold session with history, no initial prompt -> wait for user
    # - FRESH:   New session OR explicit initial prompt -> run identity hook + greeting
    _is_restore_mode = bool(session.queen_resume_from) and initial_prompt is None

    _queen_loop_config = {
        **_base_loop_config,
        "hooks": {"session_start": [_queen_identity_hook]} if not _is_restore_mode else {},
    }

    # ---- Queen event loop (AgentLoop directly, no Orchestrator) -------
    from types import SimpleNamespace

    from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
    from framework.agent_loop.types import AgentContext, AgentSpec
    from framework.storage.conversation_store import FileConversationStore

    async def _queen_loop():
        logger.debug("[_queen_loop] Starting queen loop for session %s", session.id)
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
                dynamic_prompt_provider=phase_state.get_current_prompt,
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

            async def _on_worker_done(event):
                if event.stream_id == "queen":
                    return
                if phase_state.phase == "running":
                    if event.type == EventType.EXECUTION_COMPLETED:
                        session.worker_configured = True
                        output = event.data.get("output", {})
                        output_summary = ""
                        if output:
                            for key, value in output.items():
                                val_str = str(value)
                                if len(val_str) > 200:
                                    val_str = val_str[:200] + "..."
                                output_summary += f"\n  {key}: {val_str}"
                        _out = output_summary or " (no output keys set)"
                        notification = (
                            "[WORKER_TERMINAL] Worker finished successfully.\n"
                            f"Output:{_out}\n"
                            "Report this to the user. "
                            "Ask if they want to re-run with different input "
                            "or tweak the configuration."
                        )
                    else:
                        error = event.data.get("error", "Unknown error")
                        notification = (
                            "[WORKER_TERMINAL] Worker failed.\n"
                            f"Error: {error}\n"
                            "Report this to the user and help them troubleshoot. "
                            "You can re-run with different input or escalate to "
                            "building/planning if code changes are needed."
                        )

                    await agent_loop.inject_event(notification)
                    await phase_state.switch_to_editing(source="auto")

            session.event_bus.subscribe(
                event_types=[EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED],
                handler=_on_worker_done,
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
                memory_dir=global_dir,
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
            ctx.input_data = {
                "user_request": None if _is_restore_mode else (initial_prompt or None)
            }

            logger.info(
                "Queen %s in %s phase with %d tools: %s",
                "restoring" if _is_restore_mode else "starting",
                phase_state.phase,
                len(phase_state.get_current_tools()),
                [t.name for t in phase_state.get_current_tools()],
            )

            # Run the queen -- forever-alive conversation loop
            result = await agent_loop.execute(ctx)

            if result.stop_reason == "complete":
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
