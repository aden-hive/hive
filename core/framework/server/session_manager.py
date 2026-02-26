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
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

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
    # Judge (active when worker is loaded)
    judge_task: asyncio.Task | None = None
    escalation_sub: str | None = None


class SessionManager:
    """Manages session lifecycles.

    Thread-safe via asyncio.Lock. Workers are loaded via run_in_executor
    (blocking I/O) then started on the event loop.
    """

    def __init__(self, model: str | None = None) -> None:
        self._sessions: dict[str, Session] = {}
        self._loading: set[str] = set()
        self._model = model
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
    ) -> Session:
        """Create a new session with a queen but no worker.

        The queen starts immediately with MCP coding tools.
        A worker can be loaded later via load_worker().
        """
        session = await self._create_session_core(session_id=session_id, model=model)

        # Start queen immediately (queen-only, no worker tools yet)
        await self._start_queen(session, worker_identity=None, initial_prompt=initial_prompt)

        logger.info("Session '%s' created (queen-only)", session.id)
        return session

    async def create_session_with_worker(
        self,
        agent_path: str | Path,
        agent_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
    ) -> Session:
        """Create a session and load a worker in one step.

        Backward-compatible with the old POST /api/agents flow.
        Loads the worker FIRST so the queen starts with full lifecycle
        and monitoring tools available.

        The session gets an auto-generated unique ID. The agent name
        becomes the worker_id (used by the frontend as backendAgentId).
        """
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        agent_path = Path(agent_path)
        resolved_worker_id = agent_id or agent_path.name

        # Auto-generate session ID (not the agent name)
        session = await self._create_session_core(model=model)
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
                build_worker_profile(session.worker_runtime) if session.worker_runtime else None
            )
            await self._start_queen(
                session, worker_identity=worker_identity, initial_prompt=initial_prompt
            )

            # Start health judge
            if agent_path.name != "hive_coder" and session.worker_runtime:
                await self._start_judge(session, session.runner._storage_path)

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
                ),
            )

            # Setup with session's event bus
            if runner._agent_runtime is None:
                await loop.run_in_executor(
                    None,
                    lambda: runner._setup(event_bus=session.event_bus),
                )

            runtime = runner._agent_runtime

            # Start runtime on event loop
            if runtime and not runtime.is_running:
                await runtime.start()

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

        # Start judge + notify queen (skip for hive_coder itself)
        if agent_path.name != "hive_coder" and session.worker_runtime:
            await self._start_judge(session, session.runner._storage_path)
            await self._notify_queen_worker_loaded(session)

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

        # Stop queen
        if session.queen_task is not None:
            session.queen_task.cancel()
            session.queen_task = None
        session.queen_executor = None

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

    async def _start_queen(
        self,
        session: Session,
        worker_identity: str | None,
        initial_prompt: str | None = None,
    ) -> None:
        """Start the queen executor for a session."""
        from framework.agents.hive_coder.agent import (
            queen_goal,
            queen_graph as _queen_graph,
        )
        from framework.graph.executor import GraphExecutor
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.core import Runtime

        hive_home = Path.home() / ".hive"
        queen_dir = hive_home / "queen" / "session" / session.id
        queen_dir.mkdir(parents=True, exist_ok=True)

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

        # Always register lifecycle tools — they check session.worker_runtime
        # at call time, so they work even if no worker is loaded yet.
        from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

        register_queen_lifecycle_tools(
            queen_registry,
            session=session,
            session_id=session.id,
            session_manager=self,
            manager_session_id=session.id,
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

        # Build queen graph with adjusted prompt + tools
        _orig_node = _queen_graph.nodes[0]
        base_prompt = _orig_node.system_prompt or ""

        if worker_identity is None:
            worker_identity = (
                "\n\n# Worker Profile\n"
                "No worker agent loaded. You are operating independently.\n"
                "Handle all tasks directly using your coding tools."
            )

        registered_tool_names = set(queen_registry.get_tools().keys())
        declared_tools = _orig_node.tools or []
        available_tools = [t for t in declared_tools if t in registered_tool_names]

        node_updates: dict = {
            "system_prompt": base_prompt + worker_identity,
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
                )
                session.queen_executor = executor
                logger.info(
                    "Queen starting with %d tools: %s",
                    len(queen_tools),
                    [t.name for t in queen_tools],
                )
                await executor.execute(
                    graph=queen_graph,
                    goal=queen_goal,
                    input_data={"greeting": initial_prompt or "Session started."},
                    session_state={"resume_session_id": session.id},
                )
                logger.warning("Queen executor returned (should be forever-alive)")
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

        profile = build_worker_profile(session.worker_runtime)
        await node.inject_event(f"[SYSTEM] Worker loaded.{profile}")

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

    async def shutdown_all(self) -> None:
        """Gracefully stop all sessions. Called on server shutdown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.stop_session(sid)
        logger.info("All sessions stopped")
