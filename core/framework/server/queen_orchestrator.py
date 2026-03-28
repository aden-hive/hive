"""Queen orchestrator — builds and runs the queen executor.

Extracted from SessionManager._start_queen() to keep session management
and queen orchestration concerns separate.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.server.session_manager import Session

logger = logging.getLogger(__name__)

_PRIMARY_RESULT_KEYS = (
    "result",
    "answer",
    "final_answer",
    "final_result",
    "final_output",
    "response",
    "summary",
    "report",
)
_NON_PRIMARY_KEY_TOKENS = (
    "task",
    "request",
    "prompt",
    "input",
    "brief",
    "context",
    "plan",
    "step",
    "given",
    "target",
    "relationship",
    "symbolic",
    "metadata",
    "artifact",
    "file",
    "path",
    "url",
    "link",
)
_ARTIFACT_SUFFIXES = {
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".svg",
    ".txt",
    ".xlsx",
    ".xml",
    ".yaml",
    ".yml",
}
_PRIMARY_RESULT_CHAR_LIMIT = 8000


def _stringify_worker_output_value(value: Any) -> str:
    """Convert worker output values to user-presentable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            return str(value)
    return str(value)


def _looks_like_artifact_reference(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.startswith("[Saved to "):
        return True
    if "\n" in stripped:
        return False
    if stripped.startswith(("/", "./", "../")):
        return True
    return Path(stripped).suffix.lower() in _ARTIFACT_SUFFIXES


def _is_non_primary_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _NON_PRIMARY_KEY_TOKENS)


def _select_primary_worker_result(output: dict[str, Any]) -> tuple[str, str] | None:
    """Pick the best worker output to relay verbatim, if one exists."""
    if not output:
        return None

    normalized: dict[str, str] = {}
    for key, value in output.items():
        text = _stringify_worker_output_value(value).strip()
        if text:
            normalized[key] = text

    for key in _PRIMARY_RESULT_KEYS:
        text = normalized.get(key, "")
        if text and not _looks_like_artifact_reference(text):
            return key, text

    candidates: list[tuple[str, str]] = []
    for key, text in normalized.items():
        if _is_non_primary_key(key) or _looks_like_artifact_reference(text):
            continue
        candidates.append((key, text))

    if len(candidates) == 1:
        return candidates[0]

    for key, text in candidates:
        lowered = key.lower()
        if any(token in lowered for token in ("result", "answer", "summary", "report", "response")):
            return key, text
    return None


def _format_worker_output_summary(output: dict[str, Any]) -> str:
    """Build a concise summary of worker output keys for queen handoff."""
    if not output:
        return "  (no output keys set)"

    lines: list[str] = []
    for key, value in output.items():
        preview = _stringify_worker_output_value(value).strip() or "(empty)"
        if len(preview) > 200:
            preview = preview[:200] + "..."
        lines.append(f"  {key}: {preview}")
    return "\n".join(lines)


def _build_worker_terminal_notification(output: dict[str, Any]) -> str:
    """Format a worker-completed notification for the queen."""
    summary = _format_worker_output_summary(output)
    primary = _select_primary_worker_result(output)
    if primary is None:
        return (
            "[WORKER_TERMINAL] Worker finished successfully.\n"
            f"Output summary:\n{summary}\n"
            "Report this to the user. Ask if they want to continue with another run."
        )

    key, text = primary
    if len(text) > _PRIMARY_RESULT_CHAR_LIMIT:
        text = text[:_PRIMARY_RESULT_CHAR_LIMIT].rstrip() + "\n...[truncated]"
    return (
        "[WORKER_TERMINAL] Worker finished successfully.\n"
        f"Output summary:\n{summary}\n"
        f"Primary result key: {key}\n"
        "[PRIMARY_RESULT_BEGIN]\n"
        f"{text}\n"
        "[PRIMARY_RESULT_END]\n"
        "Show the PRIMARY_RESULT to the user exactly as written between "
        "[PRIMARY_RESULT_BEGIN] and [PRIMARY_RESULT_END] before any commentary. "
        "Do not paraphrase, compress, or reformat it. After that, briefly mention "
        "any important artifacts or other output keys if useful, then ask if they "
        "want to continue with another run."
    )


def _client_input_counts_as_planning_ask(event: Any) -> bool:
    """Return True when a queen input-request should satisfy planning ask rounds.

    Explicit ask_user / ask_user_multiple calls always count. We also count
    queen auto-blocks that followed assistant text which clearly invited a
    reply, which covers Codex-style plain-text planning questions that failed
    to call ask_user. Empty/status-only auto-blocks do not count.
    """
    data = getattr(event, "data", None) or {}
    if data.get("prompt") or data.get("questions") or data.get("options"):
        return True
    if not data.get("auto_blocked"):
        return False
    requires_input = data.get("assistant_text_requires_input")
    if requires_input is None:
        requires_input = bool(data.get("assistant_text_present") and data.get("prompt"))
    return bool(requires_input)


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
    from framework.runner.tool_registry import ToolRegistry
    from framework.runtime.core import Runtime
    from framework.runtime.event_bus import AgentEvent, EventType
    from framework.tools.queen_lifecycle_tools import (
        QueenPhaseState,
        register_queen_lifecycle_tools,
    )
    from framework.tools.queen_memory_tools import register_queen_memory_tools

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
        if _client_input_counts_as_planning_ask(event):
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

    # ---- Episodic memory tools (always registered) ---------------------
    register_queen_memory_tools(queen_registry)

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
    from framework.agents.queen.queen_memory import seed_if_missing

    seed_if_missing()

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
    try:
        from framework.skills.manager import SkillsManager

        _queen_skills_mgr = SkillsManager()
        _queen_skills_mgr.load()
        phase_state.protocols_prompt = _queen_skills_mgr.protocols_prompt
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
                        # Keep the worker's primary result intact during the
                        # queen handoff so the user sees the actual answer,
                        # not just a paraphrased digest of it.
                        notification = _build_worker_terminal_notification(output)
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
