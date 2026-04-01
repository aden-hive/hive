"""Queen orchestrator — builds and runs the queen executor.

Extracted from SessionManager._start_queen() to keep session management
and queen orchestration concerns separate.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.server.session_manager import Session

logger = logging.getLogger(__name__)


async def create_queen(
    session: Session,
    session_manager: Any,
    worker_identity: str | None,
    queen_dir: Path,
    initial_prompt: str | None = None,
) -> asyncio.Task:
    """Build the queen executor and return the running asyncio task.

    Handles tool registration, phase-state initialization, prompt
    composition, persona hook setup, graph preparation, and the queen
    event loop.
    """
    from framework.agents.queen.agent import (
        queen_goal,
        queen_graph as _queen_graph,
    )
    from framework.agents.queen.nodes import (
        _QUEEN_BUILDING_TOOLS,
        _QUEEN_PLANNING_TOOLS,
        _QUEEN_RUNNING_TOOLS,
        _QUEEN_STAGING_TOOLS,
        _appendices,
        _building_knowledge,
        _planning_knowledge,
        _queen_behavior_always,
        _queen_behavior_building,
        _queen_behavior_planning,
        _queen_behavior_running,
        _queen_behavior_staging,
        _queen_identity_building,
        _queen_identity_planning,
        _queen_identity_running,
        _queen_identity_staging,
        _queen_phase_7,
        _queen_style,
        _queen_tools_building,
        _queen_tools_planning,
        _queen_tools_running,
        _queen_tools_staging,
        _shared_building_knowledge,
    )
    from framework.agents.queen.nodes.thinking_hook import select_expert_persona
    from framework.graph.event_loop_node import HookContext, HookResult
    from framework.graph.executor import GraphExecutor
    from framework.runner.mcp_registry import MCPRegistry
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.core import Runtime
    from framework.runtime.event_bus import AgentEvent, EventType
    from framework.tools.queen_lifecycle_tools import (
        QueenPhaseState,
        register_queen_lifecycle_tools,
    )
    hive_home = Path.home() / ".hive"

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
    initial_phase = "staging" if worker_identity else "planning"
    phase_state = QueenPhaseState(phase=initial_phase, event_bus=session.event_bus)
    session.phase_state = phase_state

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

    # ---- Monitoring tools (only when worker is loaded) ----------------
    if session.worker_runtime:
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        register_worker_monitoring_tools(
            queen_registry,
            session.event_bus,
            session.worker_path,
            stream_id="queen",
            worker_graph_id=session.worker_runtime._graph_id,
            default_session_id=session.id,
        )

    queen_tools = list(queen_registry.get_tools().values())
    queen_tool_executor = queen_registry.get_executor()

    # ---- Partition tools by phase ------------------------------------
    planning_names = set(_QUEEN_PLANNING_TOOLS)
    building_names = set(_QUEEN_BUILDING_TOOLS)
    staging_names = set(_QUEEN_STAGING_TOOLS)
    running_names = set(_QUEEN_RUNNING_TOOLS)

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

    # ---- Cross-session memory ----------------------------------------
    from framework.agents.queen.queen_memory_v2 import init_memory_dir

    init_memory_dir()

    # ---- Compose phase-specific prompts ------------------------------
    _orig_node = _queen_graph.nodes[0]

    if worker_identity is None:
        worker_identity = (
            "\n\n# Worker Profile\n"
            "No worker agent loaded. You are operating independently.\n"
            "Design or build the agent to solve the user's problem "
            "according to your current phase."
        )

    _planning_body = (
        _queen_style
        + _shared_building_knowledge
        + _queen_tools_planning
        + _queen_behavior_always
        + _queen_behavior_planning
        + _planning_knowledge
        + worker_identity
    )
    phase_state.prompt_planning = _queen_identity_planning + _planning_body

    _building_body = (
        _queen_style
        + _shared_building_knowledge
        + _queen_tools_building
        + _queen_behavior_always
        + _queen_behavior_building
        + _building_knowledge
        + _queen_phase_7
        + _appendices
        + worker_identity
    )
    phase_state.prompt_building = _queen_identity_building + _building_body
    phase_state.prompt_staging = (
        _queen_identity_staging
        + _queen_style
        + _queen_tools_staging
        + _queen_behavior_always
        + _queen_behavior_staging
        + worker_identity
    )
    phase_state.prompt_running = (
        _queen_identity_running
        + _queen_style
        + _queen_tools_running
        + _queen_behavior_always
        + _queen_behavior_running
        + worker_identity
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

    # ---- Persona hook ------------------------------------------------
    _session_llm = session.llm
    _session_event_bus = session.event_bus

    async def _persona_hook(ctx: HookContext) -> HookResult | None:
        persona = await select_expert_persona(ctx.trigger or "", _session_llm)
        if not persona:
            return None
        if _session_event_bus is not None:
            await _session_event_bus.publish(
                AgentEvent(
                    type=EventType.QUEEN_PERSONA_SELECTED,
                    stream_id="queen",
                    data={"persona": persona},
                )
            )
        return HookResult(system_prompt=persona + "\n\n" + phase_state.get_current_prompt())

    # ---- Graph preparation -------------------------------------------
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
            logger.warning("Queen: tools not available: %s", missing)
        node_updates["tools"] = available_tools

    adjusted_node = _orig_node.model_copy(update=node_updates)
    _queen_loop_config = {
        **(_queen_graph.loop_config or {}),
        "hooks": {"session_start": [_persona_hook]},
    }
    queen_graph = _queen_graph.model_copy(
        update={"nodes": [adjusted_node], "loop_config": _queen_loop_config}
    )

    # ---- Queen event loop --------------------------------------------
    queen_runtime = Runtime(hive_home / "queen")

    async def _queen_loop():
        try:
            executor = GraphExecutor(
                runtime=queen_runtime,
                llm=session.llm,
                tools=queen_tools,
                tool_executor=queen_tool_executor,
                event_bus=session.event_bus,
                stream_id="queen",
                storage_path=queen_dir,
                loop_config=_queen_loop_config,
                execution_id=session.id,
                dynamic_tools_provider=phase_state.get_current_tools,
                dynamic_prompt_provider=phase_state.get_current_prompt,
                iteration_metadata_provider=lambda: {"phase": phase_state.phase},
                skill_dirs=_queen_skill_dirs,
            )
            session.queen_executor = executor

            # Wire inject_notification so phase switches notify the queen LLM
            async def _inject_phase_notification(content: str) -> None:
                node = executor.node_registry.get("queen")
                if node is not None and hasattr(node, "inject_event"):
                    await node.inject_event(content)

            phase_state.inject_notification = _inject_phase_notification

            # Auto-switch to staging when worker execution finishes
            async def _on_worker_done(event):
                if event.stream_id == "queen":
                    return
                if phase_state.phase == "running":
                    if event.type == EventType.EXECUTION_COMPLETED:
                        # Mark worker as configured after first successful run
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
                            "Ask if they want to continue with another run."
                        )
                    else:  # EXECUTION_FAILED
                        error = event.data.get("error", "Unknown error")
                        notification = (
                            "[WORKER_TERMINAL] Worker failed.\n"
                            f"Error: {error}\n"
                            "Report this to the user and help them troubleshoot."
                        )

                    node = executor.node_registry.get("queen")
                    if node is not None and hasattr(node, "inject_event"):
                        await node.inject_event(notification)

                    await phase_state.switch_to_staging(source="auto")

            session.event_bus.subscribe(
                event_types=[EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED],
                handler=_on_worker_done,
            )
            session_manager._subscribe_worker_handoffs(session, executor)

            # ---- Reflection + recall memory subscriptions ----------------
            from framework.agents.queen.recall_selector import update_recall_cache
            from framework.agents.queen.reflection_agent import subscribe_reflection_triggers

            _reflection_subs = await subscribe_reflection_triggers(
                session.event_bus, queen_dir, session.llm,
            )

            async def _on_turn_complete_recall(event):
                if getattr(event, "stream_id", None) != "queen":
                    return
                try:
                    await update_recall_cache(queen_dir, session.llm, phase_state)
                except Exception:
                    logger.debug("recall: cache update failed", exc_info=True)

            _recall_sub = session.event_bus.subscribe(
                event_types=[EventType.LLM_TURN_COMPLETE],
                handler=_on_turn_complete_recall,
            )

            # Store sub IDs on session for teardown.
            session.memory_reflection_subs = _reflection_subs + [_recall_sub]

            logger.info(
                "Queen starting in %s phase with %d tools: %s",
                phase_state.phase,
                len(phase_state.get_current_tools()),
                [t.name for t in phase_state.get_current_tools()],
            )
            result = await executor.execute(
                graph=queen_graph,
                goal=queen_goal,
                input_data={"greeting": initial_prompt or "Session started."},
                session_state={"resume_session_id": session.id},
            )
            if result.success:
                logger.warning("Queen executor returned (should be forever-alive)")
            else:
                logger.error(
                    "Queen executor failed: %s",
                    result.error or "(no error message)",
                )
        except Exception:
            logger.error("Queen conversation crashed", exc_info=True)
        finally:
            session.queen_executor = None

    return asyncio.create_task(_queen_loop())
