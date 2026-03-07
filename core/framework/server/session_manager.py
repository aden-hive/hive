"""Session-primary lifecycle manager for the HTTP API server.

Sessions (queen) are the primary entity. Workers are optional and can be
loaded/unloaded while the queen stays alive.

Architecture:
- Session owns EventBus + LLM, shared with queen and worker
- Queen is always present once a session starts
- Worker is optional — loaded into an existing session
- Judge is active only when a worker is loaded
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.runtime.triggers import TriggerDefinition

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """A live session with a queen and optional worker."""

    id: str
    event_bus: Any  # EventBus — owned by session
    llm: Any  # LLMProvider — owned by session
    loaded_at: float
    # Queen (always present once started)
    queen_executor: Any = None  # GraphExecutor for queen input injection
    queen_task: asyncio.Task | None = None
    # Worker (optional)
    worker_id: str | None = None
    worker_path: Path | None = None
    runner: Any | None = None  # AgentRunner
    worker_runtime: Any | None = None  # AgentRuntime
    worker_info: Any | None = None  # AgentInfo
    # Queen phase state (building/staging/running)
    phase_state: Any = None  # QueenPhaseState
    # Judge (active when worker is loaded)
    judge_task: asyncio.Task | None = None
    escalation_sub: str | None = None
    worker_handoff_sub: str | None = None
    # Trigger definitions hoisted from worker (available but inactive)
    available_triggers: dict[str, TriggerDefinition] = field(default_factory=dict)
    # Active trigger tracking (IDs currently firing + their asyncio tasks)
    active_trigger_ids: set[str] = field(default_factory=set)
    active_timer_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    # Monotonic timestamps for next trigger fire (mirrors AgentRuntime._timer_next_fire)
    trigger_next_fire: dict[str, float] = field(default_factory=dict)
    # Session directory resumption:
    # When set, _start_queen writes queen conversations to this existing session's
    # directory instead of creating a new one.  This lets cold-restores accumulate
    # all messages in the original session folder so history is never fragmented.
    queen_resume_from: str | None = None


class SessionManager:
    """Manages session lifecycles.

    Thread-safe via asyncio.Lock. Workers are loaded via run_in_executor
    (blocking I/O) then started on the event loop.
    """

    def __init__(self, model: str | None = None, credential_store=None) -> None:
        self._sessions: dict[str, Session] = {}
        self._loading: set[str] = set()
        self._model = model
        self._credential_store = credential_store
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _create_session_core(
        self,
        session_id: str | None = None,
        model: str | None = None,
    ) -> Session:
        """Create session infrastructure (EventBus, LLM) without starting queen.

        Internal helper — use create_session() or create_session_with_worker().
        """
        from framework.config import RuntimeConfig
        from framework.llm.litellm import LiteLLMProvider
        from framework.runtime.event_bus import EventBus

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        resolved_id = session_id or f"session_{ts}_{uuid.uuid4().hex[:8]}"

        async with self._lock:
            if resolved_id in self._sessions:
                raise ValueError(f"Session '{resolved_id}' already exists")

        # Load LLM config from ~/.hive/configuration.json
        rc = RuntimeConfig(model=model or self._model or RuntimeConfig().model)

        # Session owns these — shared with queen and worker
        llm = LiteLLMProvider(
            model=rc.model,
            api_key=rc.api_key,
            api_base=rc.api_base,
            **rc.extra_kwargs,
        )
        event_bus = EventBus()

        session = Session(
            id=resolved_id,
            event_bus=event_bus,
            llm=llm,
            loaded_at=time.time(),
        )

        async with self._lock:
            self._sessions[resolved_id] = session

        return session

    async def create_session(
        self,
        session_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
    ) -> Session:
        """Create a new session with a queen but no worker.

        When ``queen_resume_from`` is set the queen writes conversation messages
        to that existing session's directory instead of creating a new one.
        This preserves full conversation history across server restarts.
        """
        session = await self._create_session_core(session_id=session_id, model=model)
        session.queen_resume_from = queen_resume_from

        # Start queen immediately (queen-only, no worker tools yet)
        await self._start_queen(session, worker_identity=None, initial_prompt=initial_prompt)

        logger.info(
            "Session '%s' created (queen-only, resume_from=%s)",
            session.id,
            queen_resume_from,
        )
        return session

    async def create_session_with_worker(
        self,
        agent_path: str | Path,
        agent_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
    ) -> Session:
        """Create a session and load a worker in one step.

        When ``queen_resume_from`` is set the queen writes conversation messages
        to that existing session's directory instead of creating a new one.
        """
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        agent_path = Path(agent_path)
        resolved_worker_id = agent_id or agent_path.name

        # Auto-generate session ID (not the agent name)
        session = await self._create_session_core(model=model)
        session.queen_resume_from = queen_resume_from
        try:
            # Load worker FIRST (before queen) so queen gets full tools
            await self._load_worker_core(
                session,
                agent_path,
                worker_id=resolved_worker_id,
                model=model,
            )

            # Start queen with worker profile + lifecycle + monitoring tools
            worker_identity = (
                build_worker_profile(session.worker_runtime, agent_path=agent_path)
                if session.worker_runtime
                else None
            )
            await self._start_queen(
                session, worker_identity=worker_identity, initial_prompt=initial_prompt
            )

        except Exception:
            # If anything fails, tear down the session
            await self.stop_session(session.id)
            raise
        return session

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    async def _load_worker_core(
        self,
        session: Session,
        agent_path: str | Path,
        worker_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """Load a worker agent into a session (core logic).

        Sets up the runner, runtime, and session fields. Does NOT start the
        judge or notify the queen — callers handle those steps.
        """
        from framework.runner import AgentRunner

        agent_path = Path(agent_path)
        resolved_worker_id = worker_id or agent_path.name

        if session.worker_runtime is not None:
            raise ValueError(f"Session '{session.id}' already has worker '{session.worker_id}'")

        async with self._lock:
            if session.id in self._loading:
                raise ValueError(f"Session '{session.id}' is currently loading a worker")
            self._loading.add(session.id)

        try:
            # Blocking I/O — load in executor
            loop = asyncio.get_running_loop()
            resolved_model = model or self._model
            runner = await loop.run_in_executor(
                None,
                lambda: AgentRunner.load(
                    agent_path,
                    model=resolved_model,
                    interactive=False,
                    skip_credential_validation=True,
                    credential_store=self._credential_store,
                ),
            )

            # Setup with session's event bus
            if runner._agent_runtime is None:
                await loop.run_in_executor(
                    None,
                    lambda: runner._setup(event_bus=session.event_bus),
                )

            runtime = runner._agent_runtime

            # Auto-hoist: extract timer/webhook triggers from worker graph
            # and store as available (inactive) trigger definitions on the session.
            # Strip them from the worker runtime so it doesn't start its own loops.
            if runtime:
                for ep in runner.graph.async_entry_points:
                    if ep.trigger_type in ("timer", "webhook"):
                        session.available_triggers[ep.id] = TriggerDefinition(
                            id=ep.id,
                            trigger_type=ep.trigger_type,
                            trigger_config=ep.trigger_config,
                            description=ep.name,
                        )
                        runtime.unregister_entry_point(ep.id)
                        logger.info(
                            "Hoisted trigger '%s' (%s) from worker to queen",
                            ep.id,
                            ep.trigger_type,
                        )

                if session.available_triggers:
                    await self._emit_trigger_events(
                        session, "available", session.available_triggers
                    )

            # Start runtime on event loop
            if runtime and not runtime.is_running:
                await runtime.start()

            # Clean up stale "active" sessions from previous (dead) processes
            self._cleanup_stale_active_sessions(agent_path)

            info = runner.info()

            # Update session
            session.worker_id = resolved_worker_id
            session.worker_path = agent_path
            session.runner = runner
            session.worker_runtime = runtime
            session.worker_info = info

            async with self._lock:
                self._loading.discard(session.id)

            logger.info(
                "Worker '%s' loaded into session '%s'",
                resolved_worker_id,
                session.id,
            )

        except Exception:
            async with self._lock:
                self._loading.discard(session.id)
            raise

    def _cleanup_stale_active_sessions(self, agent_path: Path) -> None:
        """Mark stale 'active' sessions on disk as 'cancelled'.

        When a new runtime starts, any on-disk session still marked 'active'
        is from a process that no longer exists. 'Paused' sessions are left
        intact so they remain resumable.
        """
        sessions_path = Path.home() / ".hive" / "agents" / agent_path.name / "sessions"
        if not sessions_path.exists():
            return

        for d in sessions_path.iterdir():
            if not d.is_dir() or not d.name.startswith("session_"):
                continue
            state_path = d / "state.json"
            if not state_path.exists():
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                if state.get("status") != "active":
                    continue
                state["status"] = "cancelled"
                state.setdefault("result", {})["error"] = "Stale session: runtime restarted"
                state.setdefault("timestamps", {})["updated_at"] = datetime.now().isoformat()
                state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
                logger.info(
                    "Marked stale session '%s' as cancelled for agent '%s'", d.name, agent_path.name
                )
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to clean up stale session %s: %s", d.name, e)

    async def load_worker(
        self,
        session_id: str,
        agent_path: str | Path,
        worker_id: str | None = None,
        model: str | None = None,
    ) -> Session:
        """Load a worker agent into an existing session (with running queen).

        Starts the worker runtime, health judge, and notifies the queen.
        """
        agent_path = Path(agent_path)

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")

        await self._load_worker_core(
            session,
            agent_path,
            worker_id=worker_id,
            model=model,
        )

        # Notify queen about the loaded worker (skip for hive_coder itself).
        # Health judge disabled for simplicity.
        if agent_path.name != "hive_coder" and session.worker_runtime:
            # await self._start_judge(session, session.runner._storage_path)
            await self._notify_queen_worker_loaded(session)

        # Restore previously active triggers from persisted session state
        if session.available_triggers and session.worker_runtime:
            try:
                store = session.worker_runtime._session_store
                state = await store.read_state(session_id)
                if state and state.active_triggers:
                    from framework.tools.queen_lifecycle_tools import _start_trigger_timer

                    for tid in state.active_triggers:
                        tdef = session.available_triggers.get(tid)
                        if tdef:
                            tdef.active = True
                            session.active_trigger_ids.add(tid)
                            await _start_trigger_timer(session, tid, tdef)
                            logger.info("Restored trigger timer '%s'", tid)
                        else:
                            logger.warning(
                                "Saved trigger '%s' not found in worker entry points, skipping",
                                tid,
                            )
            except Exception as e:
                logger.warning("Failed to restore active triggers: %s", e)

        # Emit SSE event so the frontend can update UI
        await self._emit_worker_loaded(session)

        return session

    async def unload_worker(self, session_id: str) -> bool:
        """Unload the worker from a session. Queen stays alive."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.worker_runtime is None:
            return False

        # Stop judge + escalation
        self._stop_judge(session)

        # Cleanup worker
        if session.runner:
            try:
                await session.runner.cleanup_async()
            except Exception as e:
                logger.error("Error cleaning up worker '%s': %s", session.worker_id, e)

        # Cancel active trigger timers
        for tid, task in session.active_timer_tasks.items():
            task.cancel()
            logger.info("Cancelled trigger timer '%s' on unload", tid)
        session.active_timer_tasks.clear()
        session.active_trigger_ids.clear()

        # Clean up hoisted triggers
        if session.available_triggers:
            await self._emit_trigger_events(session, "removed", session.available_triggers)
            session.available_triggers.clear()

        worker_id = session.worker_id
        session.worker_id = None
        session.worker_path = None
        session.runner = None
        session.worker_runtime = None
        session.worker_info = None

        # Notify queen
        await self._notify_queen_worker_unloaded(session)

        logger.info("Worker '%s' unloaded from session '%s'", worker_id, session_id)
        return True

    # ------------------------------------------------------------------
    # Session teardown
    # ------------------------------------------------------------------

    async def stop_session(self, session_id: str) -> bool:
        """Stop a session entirely — unload worker + cancel queen."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if session is None:
            return False

        # Stop judge
        self._stop_judge(session)
        if session.worker_handoff_sub is not None:
            try:
                session.event_bus.unsubscribe(session.worker_handoff_sub)
            except Exception:
                pass
            session.worker_handoff_sub = None

        # Stop queen
        if session.queen_task is not None:
            session.queen_task.cancel()
            session.queen_task = None
        session.queen_executor = None

        # Cancel active trigger timers
        for task in session.active_timer_tasks.values():
            task.cancel()
        session.active_timer_tasks.clear()

        # Cleanup worker
        if session.runner:
            try:
                await session.runner.cleanup_async()
            except Exception as e:
                logger.error("Error cleaning up worker: %s", e)

        logger.info("Session '%s' stopped", session_id)
        return True

    # ------------------------------------------------------------------
    # Queen startup
    # ------------------------------------------------------------------

    async def _handle_worker_handoff(self, session: Session, executor: Any, event: Any) -> None:
        """Route worker escalation events into the queen conversation."""
        if event.stream_id in ("queen", "judge"):
            return

        reason = str(event.data.get("reason", "")).strip()
        context = str(event.data.get("context", "")).strip()
        node_label = event.node_id or "unknown_node"
        stream_label = event.stream_id or "unknown_stream"

        handoff = (
            "[WORKER_ESCALATION_REQUEST]\n"
            f"stream_id: {stream_label}\n"
            f"node_id: {node_label}\n"
            f"reason: {reason or 'unspecified'}\n"
        )
        if context:
            handoff += f"context:\n{context}\n"

        node = executor.node_registry.get("queen")
        if node is not None and hasattr(node, "inject_event"):
            await node.inject_event(handoff, is_client_input=False)
        else:
            logger.warning("Worker handoff received but queen node not ready")

    def _subscribe_worker_handoffs(self, session: Session, executor: Any) -> None:
        """Subscribe queen to worker/subagent escalation handoff events."""
        from framework.runtime.event_bus import EventType as _ET

        if session.worker_handoff_sub is not None:
            session.event_bus.unsubscribe(session.worker_handoff_sub)
            session.worker_handoff_sub = None

        async def _on_worker_handoff(event):
            await self._handle_worker_handoff(session, executor, event)

        session.worker_handoff_sub = session.event_bus.subscribe(
            event_types=[_ET.ESCALATION_REQUESTED],
            handler=_on_worker_handoff,
        )

    async def _start_queen(
        self,
        session: Session,
        worker_identity: str | None,
        initial_prompt: str | None = None,
    ) -> None:
        """Start the queen executor for a session.

        When ``session.queen_resume_from`` is set, queen conversation messages
        are written to the ORIGINAL session's directory so the full conversation
        history accumulates in one place across server restarts.
        """
        from framework.agents.hive_coder.agent import (
            queen_goal,
            queen_graph as _queen_graph,
        )
        from framework.graph.executor import GraphExecutor
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.core import Runtime

        hive_home = Path.home() / ".hive"

        # Determine which session directory to use for queen storage.
        # When queen_resume_from is set we write to the ORIGINAL session's
        # directory so that all messages accumulate in one place.
        storage_session_id = session.queen_resume_from or session.id
        queen_dir = hive_home / "queen" / "session" / storage_session_id
        queen_dir.mkdir(parents=True, exist_ok=True)

        # Always write/update session metadata so history sidebar has correct
        # agent name, path, and last-active timestamp (important so the original
        # session directory sorts as "most recent" after a cold-restore resume).
        _meta_path = queen_dir / "meta.json"
        try:
            _agent_name = (
                session.worker_info.name
                if session.worker_info
                else (
                    str(session.worker_path.name).replace("_", " ").title()
                    if session.worker_path
                    else None
                )
            )
            _meta_path.write_text(
                json.dumps(
                    {
                        "agent_name": _agent_name,
                        "agent_path": str(session.worker_path) if session.worker_path else None,
                        "created_at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

        # Register MCP coding tools
        queen_registry = ToolRegistry()
        import framework.agents.hive_coder as _hive_coder_pkg

        hive_coder_dir = Path(_hive_coder_pkg.__file__).parent
        mcp_config = hive_coder_dir / "mcp_servers.json"
        if mcp_config.exists():
            try:
                queen_registry.load_mcp_config(mcp_config)
                logger.info("Queen: loaded MCP tools from %s", mcp_config)
            except Exception:
                logger.warning("Queen: MCP config failed to load", exc_info=True)

        # Phase state for building/running phase switching
        from framework.tools.queen_lifecycle_tools import (
            QueenPhaseState,
            register_queen_lifecycle_tools,
        )

        # Start in staging when the caller provided an agent, building otherwise.
        initial_phase = "staging" if worker_identity else "building"
        phase_state = QueenPhaseState(phase=initial_phase, event_bus=session.event_bus)
        session.phase_state = phase_state

        # Always register lifecycle tools — they check session.worker_runtime
        # at call time, so they work even if no worker is loaded yet.
        register_queen_lifecycle_tools(
            queen_registry,
            session=session,
            session_id=session.id,
            session_manager=self,
            manager_session_id=session.id,
            phase_state=phase_state,
        )

        # Monitoring tools need concrete worker paths — only register when present
        if session.worker_runtime:
            from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

            register_worker_monitoring_tools(
                queen_registry,
                session.event_bus,
                session.worker_path,
                stream_id="queen",
                worker_graph_id=session.worker_runtime._graph_id,
            )

        queen_tools = list(queen_registry.get_tools().values())
        queen_tool_executor = queen_registry.get_executor()

        # Partition tools into phase-specific sets and import prompt segments
        from framework.agents.hive_coder.nodes import (
            _QUEEN_BUILDING_TOOLS,
            _QUEEN_RUNNING_TOOLS,
            _QUEEN_STAGING_TOOLS,
            _package_builder_knowledge,
            _appendices,
            _queen_behavior_always,
            _queen_behavior_building,
            _queen_behavior_running,
            _queen_behavior_staging,
            _queen_identity_building,
            _queen_identity_running,
            _queen_identity_staging,
            _queen_phase_7,
            _queen_style,
            _queen_tools_building,
            _queen_tools_running,
            _queen_tools_staging,
        )

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

        phase_state.building_tools = [t for t in queen_tools if t.name in building_names]
        phase_state.staging_tools = [t for t in queen_tools if t.name in staging_names]
        phase_state.running_tools = [t for t in queen_tools if t.name in running_names]

        # Build queen graph with adjusted prompt + tools
        _orig_node = _queen_graph.nodes[0]

        if worker_identity is None:
            worker_identity = (
                "\n\n# Worker Profile\n"
                "No worker agent loaded. You are operating independently.\n"
                "Handle all tasks directly using your coding tools."
            )

        # Compose phase-specific prompts
        phase_state.prompt_building = (
            _queen_identity_building
            + _queen_style
            + _queen_tools_building
            + _queen_behavior_always
            + _queen_behavior_building
            + _package_builder_knowledge
            + _queen_phase_7
            + _appendices
            + worker_identity
        )
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

        # Use the initial phase prompt as the node's system_prompt
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
        queen_graph = _queen_graph.model_copy(update={"nodes": [adjusted_node]})

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
                    loop_config=queen_graph.loop_config,
                    execution_id=session.id,
                    dynamic_tools_provider=phase_state.get_current_tools,
                    dynamic_prompt_provider=phase_state.get_current_prompt,
                )
                session.queen_executor = executor

                # Wire inject_notification so phase switches notify the queen LLM
                async def _inject_phase_notification(content: str) -> None:
                    node = executor.node_registry.get("queen")
                    if node is not None and hasattr(node, "inject_event"):
                        await node.inject_event(content)

                phase_state.inject_notification = _inject_phase_notification

                # Auto-switch to staging when worker execution finishes naturally
                # and notify the queen about the termination
                from framework.runtime.event_bus import EventType as _ET

                async def _on_worker_done(event):
                    if event.stream_id == "queen":
                        return
                    if phase_state.phase == "running":
                        # Build termination notification for the queen
                        if event.type == _ET.EXECUTION_COMPLETED:
                            output = event.data.get("output", {})
                            output_summary = ""
                            if output:
                                # Summarize key outputs for the queen
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

                        # Inject notification to queen before phase switch
                        node = executor.node_registry.get("queen")
                        if node is not None and hasattr(node, "inject_event"):
                            await node.inject_event(notification)

                        await phase_state.switch_to_staging(source="auto")

                session.event_bus.subscribe(
                    event_types=[_ET.EXECUTION_COMPLETED, _ET.EXECUTION_FAILED],
                    handler=_on_worker_done,
                )
                self._subscribe_worker_handoffs(session, executor)

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

        session.queen_task = asyncio.create_task(_queen_loop())

    # ------------------------------------------------------------------
    # Judge startup / teardown
    # ------------------------------------------------------------------

    async def _start_judge(
        self,
        session: Session,
        worker_storage_path: str | Path,
    ) -> None:
        """Start the health judge for a session's worker."""
        from framework.graph.executor import GraphExecutor
        from framework.monitoring import judge_goal, judge_graph
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.core import Runtime
        from framework.runtime.event_bus import EventType as _ET
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        worker_storage_path = Path(worker_storage_path)

        try:
            # Monitoring tools
            monitoring_registry = ToolRegistry()
            register_worker_monitoring_tools(
                monitoring_registry,
                session.event_bus,
                worker_storage_path,
                worker_graph_id=session.worker_runtime._graph_id,
            )

            hive_home = Path.home() / ".hive"
            judge_dir = hive_home / "judge" / "session" / session.id
            judge_dir.mkdir(parents=True, exist_ok=True)

            judge_runtime = Runtime(hive_home / "judge")
            monitoring_tools = list(monitoring_registry.get_tools().values())
            monitoring_executor = monitoring_registry.get_executor()

            async def _judge_loop():
                interval = 300  # 5 minutes between checks
                # Wait before the first check — let the worker actually do something
                await asyncio.sleep(interval)
                while True:
                    try:
                        executor = GraphExecutor(
                            runtime=judge_runtime,
                            llm=session.llm,
                            tools=monitoring_tools,
                            tool_executor=monitoring_executor,
                            event_bus=session.event_bus,
                            stream_id="judge",
                            storage_path=judge_dir,
                            loop_config=judge_graph.loop_config,
                        )
                        await executor.execute(
                            graph=judge_graph,
                            goal=judge_goal,
                            input_data={
                                "event": {"source": "timer", "reason": "scheduled"},
                            },
                            session_state={"resume_session_id": session.id},
                        )
                    except Exception:
                        logger.error("Health judge tick failed", exc_info=True)
                    await asyncio.sleep(interval)

            session.judge_task = asyncio.create_task(_judge_loop())

            # Escalation: judge → queen
            async def _on_escalation(event):
                ticket = event.data.get("ticket", {})
                executor = session.queen_executor
                if executor is None:
                    logger.warning("Escalation received but queen executor is None")
                    return
                node = executor.node_registry.get("queen")
                if node is not None and hasattr(node, "inject_event"):
                    msg = "[ESCALATION TICKET from Health Judge]\n" + json.dumps(
                        ticket, indent=2, ensure_ascii=False
                    )
                    await node.inject_event(msg)
                else:
                    logger.warning("Escalation received but queen node not ready")

            session.escalation_sub = session.event_bus.subscribe(
                event_types=[_ET.WORKER_ESCALATION_TICKET],
                handler=_on_escalation,
            )

            logger.info("Judge started for session '%s'", session.id)

        except Exception as e:
            logger.error(
                "Failed to start judge for session '%s': %s",
                session.id,
                e,
                exc_info=True,
            )

    def _stop_judge(self, session: Session) -> None:
        """Cancel judge task and unsubscribe escalation events."""
        if session.judge_task is not None:
            session.judge_task.cancel()
            session.judge_task = None
        if session.escalation_sub is not None:
            try:
                session.event_bus.unsubscribe(session.escalation_sub)
            except Exception:
                pass
            session.escalation_sub = None

    # ------------------------------------------------------------------
    # Queen notifications
    # ------------------------------------------------------------------

    async def _notify_queen_worker_loaded(self, session: Session) -> None:
        """Inject a system message into the queen about the loaded worker."""
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        executor = session.queen_executor
        if executor is None:
            return
        node = executor.node_registry.get("queen")
        if node is None or not hasattr(node, "inject_event"):
            return

        profile = build_worker_profile(session.worker_runtime, agent_path=session.worker_path)

        # Append available trigger info so the queen knows what's schedulable
        trigger_lines = ""
        if session.available_triggers:
            parts = []
            for t in session.available_triggers.values():
                cfg = t.trigger_config
                detail = cfg.get("cron") or f"every {cfg.get('interval_minutes', '?')} min"
                parts.append(f"  - {t.id} ({t.trigger_type}: {detail})")
            trigger_lines = "\n\nAvailable triggers (inactive — use set_trigger to activate):\n" + "\n".join(parts)

        await node.inject_event(f"[SYSTEM] Worker loaded.{profile}{trigger_lines}")

    async def _emit_worker_loaded(self, session: Session) -> None:
        """Publish a WORKER_LOADED event so the frontend can update."""
        from framework.runtime.event_bus import AgentEvent, EventType

        info = session.worker_info
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.WORKER_LOADED,
                stream_id="queen",
                data={
                    "worker_id": session.worker_id,
                    "worker_name": info.name if info else session.worker_id,
                    "agent_path": str(session.worker_path) if session.worker_path else "",
                    "goal": info.goal_name if info else "",
                    "node_count": info.node_count if info else 0,
                },
            )
        )

    async def _notify_queen_worker_unloaded(self, session: Session) -> None:
        """Notify the queen that the worker has been unloaded."""
        executor = session.queen_executor
        if executor is None:
            return
        node = executor.node_registry.get("queen")
        if node is None or not hasattr(node, "inject_event"):
            return

        await node.inject_event(
            "[SYSTEM] Worker unloaded. You are now operating independently. "
            "Handle all tasks directly using your coding tools."
        )

    async def _emit_trigger_events(
        self,
        session: Session,
        kind: str,
        triggers: dict[str, TriggerDefinition],
    ) -> None:
        """Emit TRIGGER_AVAILABLE or TRIGGER_REMOVED events for each trigger."""
        from framework.runtime.event_bus import AgentEvent, EventType

        event_type = (
            EventType.TRIGGER_AVAILABLE if kind == "available" else EventType.TRIGGER_REMOVED
        )
        for t in triggers.values():
            await session.event_bus.publish(
                AgentEvent(
                    type=event_type,
                    stream_id="queen",
                    data={
                        "trigger_id": t.id,
                        "trigger_type": t.trigger_type,
                        "trigger_config": t.trigger_config,
                    },
                )
            )

    async def revive_queen(self, session: Session, initial_prompt: str | None = None) -> None:
        """Revive a dead queen executor on an existing session.

        Restarts the queen with the same session context (worker profile, tools, etc.).
        """
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        # Build worker identity if worker is loaded
        worker_identity = (
            build_worker_profile(session.worker_runtime, agent_path=session.worker_path)
            if session.worker_runtime
            else None
        )

        # Start queen with existing session context
        await self._start_queen(
            session, worker_identity=worker_identity, initial_prompt=initial_prompt
        )

        logger.info("Queen revived for session '%s'", session.id)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_session_by_worker_id(self, worker_id: str) -> Session | None:
        """Find a session by its loaded worker's ID."""
        for s in self._sessions.values():
            if s.worker_id == worker_id:
                return s
        return None

    def get_session_for_agent(self, agent_id: str) -> Session | None:
        """Resolve an agent_id to a session (backward compat).

        Checks session.id first, then session.worker_id.
        """
        s = self._sessions.get(agent_id)
        if s:
            return s
        return self.get_session_by_worker_id(agent_id)

    def is_loading(self, session_id: str) -> bool:
        return session_id in self._loading

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Cold session helpers (disk-only, no live runtime required)
    # ------------------------------------------------------------------

    @staticmethod
    def get_cold_session_info(session_id: str) -> dict | None:
        """Return disk metadata for a session that is no longer live in memory.

        Checks whether queen conversation files exist at
        ~/.hive/queen/session/{session_id}/conversations/.  Returns None when
        no data is found so callers can fall through to a 404.
        """
        queen_dir = Path.home() / ".hive" / "queen" / "session" / session_id
        convs_dir = queen_dir / "conversations"
        if not convs_dir.exists():
            return None

        # Check whether any message part files are actually present
        has_messages = False
        try:
            for node_dir in convs_dir.iterdir():
                if not node_dir.is_dir():
                    continue
                parts_dir = node_dir / "parts"
                if parts_dir.exists() and any(f.suffix == ".json" for f in parts_dir.iterdir()):
                    has_messages = True
                    break
        except OSError:
            pass

        try:
            created_at = queen_dir.stat().st_ctime
        except OSError:
            created_at = 0.0

        # Read extra metadata written at session start
        agent_name: str | None = None
        agent_path: str | None = None
        meta_path = queen_dir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agent_name = meta.get("agent_name")
                agent_path = meta.get("agent_path")
                created_at = meta.get("created_at") or created_at
            except (json.JSONDecodeError, OSError):
                pass

        return {
            "session_id": session_id,
            "cold": True,
            "live": False,
            "has_messages": has_messages,
            "created_at": created_at,
            "agent_name": agent_name,
            "agent_path": agent_path,
        }

    @staticmethod
    def list_cold_sessions() -> list[dict]:
        """Return metadata for every queen session directory on disk, newest first."""
        queen_sessions_dir = Path.home() / ".hive" / "queen" / "session"
        if not queen_sessions_dir.exists():
            return []

        results: list[dict] = []
        try:
            entries = sorted(
                queen_sessions_dir.iterdir(),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            return []

        for d in entries:
            if not d.is_dir():
                continue
            try:
                created_at = d.stat().st_ctime
            except OSError:
                created_at = 0.0
            agent_name: str | None = None
            agent_path: str | None = None
            meta_path = d / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    agent_name = meta.get("agent_name")
                    agent_path = meta.get("agent_path")
                    created_at = meta.get("created_at") or created_at
                except (json.JSONDecodeError, OSError):
                    pass

            # Build a quick preview of the last human/assistant exchange.
            # We read all conversation parts, filter to client-facing messages,
            # and return the last assistant message content as a snippet.
            last_message: str | None = None
            message_count: int = 0
            convs_dir = d / "conversations"
            if convs_dir.exists():
                try:
                    all_parts: list[dict] = []
                    for node_dir in convs_dir.iterdir():
                        if not node_dir.is_dir():
                            continue
                        parts_dir = node_dir / "parts"
                        if not parts_dir.exists():
                            continue
                        for part_file in sorted(parts_dir.iterdir()):
                            if part_file.suffix != ".json":
                                continue
                            try:
                                part = json.loads(part_file.read_text(encoding="utf-8"))
                                part.setdefault("created_at", part_file.stat().st_mtime)
                                all_parts.append(part)
                            except (json.JSONDecodeError, OSError):
                                continue
                    # Filter to client-facing messages only
                    client_msgs = [
                        p
                        for p in all_parts
                        if not p.get("is_transition_marker")
                        and p.get("role") != "tool"
                        and not (p.get("role") == "assistant" and p.get("tool_calls"))
                    ]
                    client_msgs.sort(key=lambda m: m.get("created_at", m.get("seq", 0)))
                    message_count = len(client_msgs)
                    # Last assistant message as preview snippet
                    for msg in reversed(client_msgs):
                        content = msg.get("content") or ""
                        if isinstance(content, list):
                            # Anthropic-style content blocks
                            content = " ".join(
                                b.get("text", "")
                                for b in content
                                if isinstance(b, dict) and b.get("type") == "text"
                            )
                        if content and msg.get("role") == "assistant":
                            last_message = content[:120].strip()
                            break
                except OSError:
                    pass

            results.append(
                {
                    "session_id": d.name,
                    "cold": True,  # caller overrides for live sessions
                    "live": False,
                    "has_messages": convs_dir.exists() and message_count > 0,
                    "created_at": created_at,
                    "agent_name": agent_name,
                    "agent_path": agent_path,
                    "last_message": last_message,
                    "message_count": message_count,
                }
            )

        return results

    async def shutdown_all(self) -> None:
        """Gracefully stop all sessions. Called on server shutdown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.stop_session(sid)
        logger.info("All sessions stopped")
