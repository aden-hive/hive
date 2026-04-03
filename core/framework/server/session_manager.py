"""Session-primary lifecycle manager for the HTTP API server.

Sessions (queen) are the primary entity. Workers are optional and can be
loaded/unloaded while the queen stays alive.

Architecture:
- Session owns EventBus + LLM, shared with queen and worker
- Queen is always present once a session starts
- Worker is optional — loaded into an existing session
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
    # Loaded graph (optional)
    graph_id: str | None = None
    worker_path: Path | None = None
    runner: Any | None = None  # AgentRunner
    graph_runtime: Any | None = None  # AgentRuntime
    worker_info: Any | None = None  # AgentInfo
    # Queen phase state (building/staging/running)
    phase_state: Any = None  # QueenPhaseState
    # Worker handoff subscription
    worker_handoff_sub: str | None = None
    # Memory reflection + recall subscriptions
    memory_reflection_subs: list = field(default_factory=list)  # list[str]
    # Worker colony memory subscriptions
    worker_memory_subs: list = field(default_factory=list)  # list[str]
    # Per-execution colony recall cache for worker prompts
    worker_colony_recall_blocks: dict[str, str] = field(default_factory=dict)
    # Trigger definitions loaded from agent's triggers.json (available but inactive)
    available_triggers: dict[str, TriggerDefinition] = field(default_factory=dict)
    # Active trigger tracking (IDs currently firing + their asyncio tasks)
    active_trigger_ids: set[str] = field(default_factory=set)
    active_timer_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    # Queen-owned webhook server (lazy singleton, created on first webhook trigger activation)
    queen_webhook_server: Any = None
    # EventBus subscription IDs for active webhook triggers (trigger_id -> sub_id)
    active_webhook_subs: dict[str, str] = field(default_factory=dict)
    # True after first successful worker execution (gates trigger delivery)
    worker_configured: bool = False
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

        Internal helper — use create_session() or create_session_with_worker_graph().
        """
        from framework.config import RuntimeConfig, get_hive_config
        from framework.runtime.event_bus import EventBus

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        resolved_id = session_id or f"session_{ts}_{uuid.uuid4().hex[:8]}"

        async with self._lock:
            if resolved_id in self._sessions:
                raise ValueError(f"Session '{resolved_id}' already exists")

        # Load LLM config from ~/.hive/configuration.json
        rc = RuntimeConfig(model=model or self._model or RuntimeConfig().model)

        # Session owns these — shared with queen and worker
        llm_config = get_hive_config().get("llm", {})
        if llm_config.get("use_antigravity_subscription"):
            from framework.llm.antigravity import AntigravityProvider

            llm = AntigravityProvider(model=rc.model)
        else:
            from framework.llm.litellm import LiteLLMProvider

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
        # Reuse the original session ID when cold-restoring
        resolved_session_id = queen_resume_from or session_id
        session = await self._create_session_core(session_id=resolved_session_id, model=model)
        session.queen_resume_from = queen_resume_from

        # Start queen immediately (queen-only, no worker tools yet)
        await self._start_queen(session, worker_identity=None, initial_prompt=initial_prompt)

        logger.info(
            "Session '%s' created (queen-only, resume_from=%s)",
            session.id,
            queen_resume_from,
        )
        return session

    async def create_session_with_worker_graph(
        self,
        agent_path: str | Path,
        agent_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
    ) -> Session:
        """Create a session and load a worker in one step.

        When ``queen_resume_from`` is set the session reuses the original session
        ID so the frontend sees a single continuous session.  The queen writes
        conversation messages to that existing directory, preserving full history.
        """
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        agent_path = Path(agent_path)
        resolved_graph_id = agent_id or agent_path.name

        # When cold-restoring, check meta.json for the phase — if the agent
        # was still being built we must NOT try to load the worker (the code
        # is incomplete and will fail to import).
        if queen_resume_from:
            _resume_phase = None
            _meta_path = (
                Path.home() / ".hive" / "queen" / "session" / queen_resume_from / "meta.json"
            )
            if _meta_path.exists():
                try:
                    _meta = json.loads(_meta_path.read_text(encoding="utf-8"))
                    _resume_phase = _meta.get("phase")
                except (json.JSONDecodeError, OSError):
                    pass
            if _resume_phase in ("building", "planning"):
                # Fall back to queen-only session — cold resume handler in
                # _start_queen will set phase_state.agent_path and switch to
                # the correct phase.
                return await self.create_session(
                    session_id=session_id,
                    model=model,
                    initial_prompt=initial_prompt,
                    queen_resume_from=queen_resume_from,
                )

        # Reuse the original session ID when cold-restoring so the frontend
        # sees one continuous session instead of a new one each time.
        session = await self._create_session_core(
            session_id=queen_resume_from,
            model=model,
        )
        session.queen_resume_from = queen_resume_from
        try:
            # Load the graph FIRST (before queen) so queen gets full tools
            await self._load_worker_core(
                session,
                agent_path,
                graph_id=resolved_graph_id,
                model=model,
            )

            # Restore active triggers from persisted state (cold restore)
            await self._restore_active_triggers(session, session.id)

            # Start queen with worker profile + lifecycle + monitoring tools
            worker_identity = (
                build_worker_profile(session.graph_runtime, agent_path=agent_path)
                if session.graph_runtime
                else None
            )
            await self._start_queen(
                session, worker_identity=worker_identity, initial_prompt=initial_prompt
            )

        except Exception:
            if queen_resume_from:
                # Cold restore: worker load failed (e.g. incomplete code from a
                # building session).  Fall back to queen-only so the user can
                # continue the conversation and fix / rebuild the agent.
                logger.warning(
                    "Cold restore: worker load failed for '%s', falling back to queen-only",
                    agent_path,
                    exc_info=True,
                )
                await self.stop_session(session.id)
                return await self.create_session(
                    session_id=session_id,
                    model=model,
                    initial_prompt=initial_prompt,
                    queen_resume_from=queen_resume_from,
                )
            # If anything fails (non-cold-restore), tear down the session
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
        graph_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """Load a graph into a session (core logic).

        Sets up the runner, runtime, and session fields. Does NOT notify
        the queen — callers handle that step.
        """
        from framework.runner import AgentRunner

        agent_path = Path(agent_path)
        resolved_graph_id = graph_id or agent_path.name

        if session.graph_runtime is not None:
            raise ValueError(f"Session '{session.id}' already has graph '{session.graph_id}'")

        async with self._lock:
            if session.id in self._loading:
                raise ValueError(f"Session '{session.id}' is currently loading a graph")
            self._loading.add(session.id)

        try:
            # Blocking I/O — load in executor
            loop = asyncio.get_running_loop()
            # By default, workers share the session's LLM with the queen so
            # execution and memory reflection/recall stay on the same model.
            session_model = getattr(session.llm, "model", None)
            resolved_model = model or session_model or self._model
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

            if model is None:
                runner._llm = session.llm

            # Setup with session's event bus
            if runner._agent_runtime is None:
                await loop.run_in_executor(
                    None,
                    lambda: runner._setup(event_bus=session.event_bus),
                )

            runtime = runner._agent_runtime

            if runtime is not None:
                runtime._dynamic_memory_provider_factory = (
                    lambda execution_id, session=session: (
                        lambda execution_id=execution_id, session=session: session.worker_colony_recall_blocks.get(
                            execution_id,
                            "",
                        )
                    )
                )

            # Load triggers from the agent's triggers.json definition file.
            from framework.tools.queen_lifecycle_tools import _read_agent_triggers_json

            for tdata in _read_agent_triggers_json(agent_path):
                tid = tdata.get("id", "")
                ttype = tdata.get("trigger_type", "")
                if tid and ttype in ("timer", "webhook"):
                    session.available_triggers[tid] = TriggerDefinition(
                        id=tid,
                        trigger_type=ttype,
                        trigger_config=tdata.get("trigger_config", {}),
                        description=tdata.get("name", tid),
                        task=tdata.get("task", ""),
                    )
                    logger.info("Loaded trigger '%s' (%s) from triggers.json", tid, ttype)

            if session.available_triggers:
                await self._emit_trigger_events(session, "available", session.available_triggers)

            # Start runtime on event loop
            if runtime and not runtime.is_running:
                await runtime.start()

            # Clean up stale "active" sessions from previous (dead) processes
            self._cleanup_stale_active_sessions(agent_path)

            info = runner.info()

            # Update session
            session.graph_id = resolved_graph_id
            session.worker_path = agent_path
            session.runner = runner
            session.graph_runtime = runtime
            session.worker_info = info

            # Colony memory is additive; worker loading should still succeed if
            # that optional subscription path hits an import/runtime issue while
            # restoring an older session.
            try:
                await self._subscribe_worker_colony_memory(session)
            except Exception:
                logger.warning(
                    "Worker colony memory subscription failed for '%s'; continuing without it",
                    resolved_graph_id,
                    exc_info=True,
                )

            async with self._lock:
                self._loading.discard(session.id)

            logger.info(
                "Worker '%s' loaded into session '%s'",
                resolved_graph_id,
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

        Two-layer protection against corrupting live sessions:
        1. In-memory: skip any session ID currently tracked in self._sessions
           (guaranteed alive in this process).
        2. PID validation: if state.json contains a ``pid`` field, check whether
           that process is still running on the host. If it is, the session is
           owned by another healthy worker process, so leave it alone.
        """
        sessions_path = Path.home() / ".hive" / "agents" / agent_path.name / "sessions"
        if not sessions_path.exists():
            return

        live_session_ids = set(self._sessions.keys())

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

                # Layer 1: skip sessions that are alive in this process
                session_id = state.get("session_id", d.name)
                if session_id in live_session_ids or d.name in live_session_ids:
                    logger.debug(
                        "Skipping live in-memory session '%s' during stale cleanup",
                        d.name,
                    )
                    continue

                # Layer 2: skip sessions whose owning process is still alive
                recorded_pid = state.get("pid")
                if recorded_pid is not None and self._is_pid_alive(recorded_pid):
                    logger.debug(
                        "Skipping session '%s' — owning process %d is still running",
                        d.name,
                        recorded_pid,
                    )
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

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """Check whether a process with the given PID is still running."""
        import os
        import platform

        if platform.system() == "Windows":
            import ctypes

            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                # 5 is ERROR_ACCESS_DENIED, meaning the process exists but is protected
                return kernel32.GetLastError() == 5

            exit_code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            # 259 is STILL_ACTIVE
            return exit_code.value == 259
        else:
            try:
                os.kill(pid, 0)
            except OSError:
                return False
            return True

    async def _restore_active_triggers(self, session: "Session", session_id: str) -> None:
        """Restore previously active triggers from persisted session state.

        Called after worker loading to restart any timer/webhook triggers
        that were active before a server restart.
        """
        if not session.available_triggers or not session.graph_runtime:
            return
        try:
            store = session.graph_runtime._session_store
            state = await store.read_state(session_id)
            if state and state.active_triggers:
                from framework.tools.queen_lifecycle_tools import (
                    _start_trigger_timer,
                    _start_trigger_webhook,
                )

                saved_tasks = getattr(state, "trigger_tasks", {}) or {}
                for tid in state.active_triggers:
                    tdef = session.available_triggers.get(tid)
                    if tdef:
                        # Restore user-configured task override
                        saved_task = saved_tasks.get(tid, "")
                        if saved_task:
                            tdef.task = saved_task
                        tdef.active = True
                        session.active_trigger_ids.add(tid)
                        if tdef.trigger_type == "timer":
                            await _start_trigger_timer(session, tid, tdef)
                            logger.info("Restored trigger timer '%s'", tid)
                        elif tdef.trigger_type == "webhook":
                            await _start_trigger_webhook(session, tid, tdef)
                            logger.info("Restored webhook trigger '%s'", tid)
                    else:
                        logger.warning(
                            "Saved trigger '%s' not found in worker entry points, skipping",
                            tid,
                        )

            # Restore worker_configured flag
            if state and getattr(state, "worker_configured", False):
                session.worker_configured = True
        except Exception as e:
            logger.warning("Failed to restore active triggers: %s", e)

    async def load_graph(
        self,
        session_id: str,
        agent_path: str | Path,
        graph_id: str | None = None,
        model: str | None = None,
    ) -> Session:
        """Load a graph into an existing session (with running queen).

        Starts the graph runtime and notifies the queen.
        """
        agent_path = Path(agent_path)

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")

        await self._load_worker_core(
            session,
            agent_path,
            graph_id=graph_id,
            model=model,
        )

        # Notify queen about the loaded worker (skip for queen itself).
        if agent_path.name != "queen" and session.graph_runtime:
            await self._notify_queen_graph_loaded(session)

        # Update meta.json so cold-restore can discover this session by agent_path
        storage_session_id = session.queen_resume_from or session.id
        meta_path = Path.home() / ".hive" / "queen" / "session" / storage_session_id / "meta.json"
        try:
            _agent_name = (
                session.worker_info.name
                if session.worker_info
                else str(agent_path.name).replace("_", " ").title()
            )
            existing_meta = {}
            if meta_path.exists():
                existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_meta["agent_name"] = _agent_name
            existing_meta["agent_path"] = (
                str(session.worker_path) if session.worker_path else str(agent_path)
            )
            meta_path.write_text(json.dumps(existing_meta), encoding="utf-8")
        except OSError:
            pass

        await self._restore_active_triggers(session, session_id)

        # Emit SSE event so the frontend can update UI
        await self._emit_graph_loaded(session)

        return session

    async def unload_graph(self, session_id: str) -> bool:
        """Unload the worker from a session. Queen stays alive."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.graph_runtime is None:
            return False

        # Cleanup worker
        if session.runner:
            try:
                await session.runner.cleanup_async()
            except Exception as e:
                logger.error("Error cleaning up graph '%s': %s", session.graph_id, e)

        # Cancel active trigger timers
        for tid, task in session.active_timer_tasks.items():
            task.cancel()
            logger.info("Cancelled trigger timer '%s' on unload", tid)
        session.active_timer_tasks.clear()

        # Unsubscribe webhook handlers (server stays alive — queen-owned)
        for sub_id in session.active_webhook_subs.values():
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.active_webhook_subs.clear()
        session.active_trigger_ids.clear()

        # Clean up triggers
        if session.available_triggers:
            await self._emit_trigger_events(session, "removed", session.available_triggers)
            session.available_triggers.clear()

        for sub_id in session.worker_memory_subs:
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.worker_memory_subs.clear()
        session.worker_colony_recall_blocks.clear()

        graph_id = session.graph_id
        session.graph_id = None
        session.worker_path = None
        session.runner = None
        session.graph_runtime = None
        session.worker_info = None

        # Notify queen
        await self._notify_queen_worker_unloaded(session)

        logger.info("Graph '%s' unloaded from session '%s'", graph_id, session_id)
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

        # Capture session data for memory consolidation before teardown
        _llm = getattr(session, "llm", None)
        _storage_id = getattr(session, "queen_resume_from", None) or session_id
        _session_dir = Path.home() / ".hive" / "queen" / "session" / _storage_id

        if session.worker_handoff_sub is not None:
            try:
                session.event_bus.unsubscribe(session.worker_handoff_sub)
            except Exception:
                pass
            session.worker_handoff_sub = None

        for sub_id in session.worker_memory_subs:
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.worker_memory_subs.clear()
        session.worker_colony_recall_blocks.clear()

        # Stop queen and memory reflection/recall subscriptions
        for sub_id in session.memory_reflection_subs:
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.memory_reflection_subs.clear()
        if session.queen_task is not None:
            session.queen_task.cancel()
            session.queen_task = None
        session.queen_executor = None

        # Cancel active trigger timers
        for task in session.active_timer_tasks.values():
            task.cancel()
        session.active_timer_tasks.clear()

        # Unsubscribe webhook handlers and stop queen webhook server
        for sub_id in session.active_webhook_subs.values():
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.active_webhook_subs.clear()
        if session.queen_webhook_server is not None:
            try:
                await session.queen_webhook_server.stop()
            except Exception:
                logger.error("Error stopping queen webhook server", exc_info=True)
            session.queen_webhook_server = None

        # Cleanup worker
        if session.runner:
            try:
                await session.runner.cleanup_async()
            except Exception as e:
                logger.error("Error cleaning up worker: %s", e)

        # Final long reflection — fire-and-forget so teardown isn't blocked.
        if _llm is not None:
            import asyncio

            from framework.agents.queen.queen_memory_v2 import colony_memory_dir
            from framework.agents.queen.reflection_agent import run_long_reflection

            asyncio.create_task(
                run_long_reflection(_llm, memory_dir=colony_memory_dir(_storage_id), caller="queen"),
                name=f"queen-memory-long-reflection-{session_id}",
            )

        # Close per-session event log
        session.event_bus.close_session_log()

        logger.info("Session '%s' stopped", session_id)
        return True

    # ------------------------------------------------------------------
    # Queen startup
    # ------------------------------------------------------------------

    async def _handle_worker_handoff(self, session: Session, executor: Any, event: Any) -> None:
        """Route worker escalation events into the queen conversation."""
        if event.stream_id == "queen":
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

    async def _subscribe_worker_colony_memory(self, session: Session) -> None:
        """Subscribe shared colony reflection/recall for top-level worker runs."""
        for sub_id in session.worker_memory_subs:
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.worker_memory_subs.clear()
        session.worker_colony_recall_blocks.clear()

        runtime = session.graph_runtime
        if runtime is None:
            return

        worker_sessions_dir = getattr(runtime, "_session_store", None)
        worker_sessions_dir = getattr(worker_sessions_dir, "sessions_dir", None)
        if worker_sessions_dir is None:
            return

        from framework.agents.queen.queen_memory_v2 import colony_memory_dir, init_memory_dir
        from framework.agents.queen.reflection_agent import subscribe_worker_memory_triggers

        colony_dir = colony_memory_dir(session.id)
        init_memory_dir(colony_dir, migrate_legacy=True)

        runtime._dynamic_memory_provider_factory = (
            lambda execution_id, session=session: (
                lambda execution_id=execution_id, session=session: session.worker_colony_recall_blocks.get(
                    execution_id,
                    "",
                )
            )
        )

        # Colony memory config for reflection-at-handoff
        runtime._colony_memory_dir = colony_dir
        runtime._colony_worker_sessions_dir = worker_sessions_dir
        runtime._colony_recall_cache = session.worker_colony_recall_blocks
        runtime._colony_reflect_llm = session.llm

        session.worker_memory_subs = await subscribe_worker_memory_triggers(
            session.event_bus,
            session.llm,
            worker_sessions_dir=worker_sessions_dir,
            colony_memory_dir=colony_dir,
            recall_cache=session.worker_colony_recall_blocks,
        )

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
        from framework.server.queen_orchestrator import create_queen

        logger.debug("[_start_queen] Starting for session %s, current queen_executor=%s", session.id, session.queen_executor)

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
            # Merge into existing meta.json to preserve fields written by
            # _update_meta_json (e.g. phase, agent_path set during building).
            _existing_meta: dict = {}
            if _meta_path.exists():
                try:
                    _existing_meta = json.loads(_meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            _new_meta: dict = {"created_at": time.time()}
            if _agent_name is not None:
                _new_meta["agent_name"] = _agent_name
            if session.worker_path is not None:
                _new_meta["agent_path"] = str(session.worker_path)
            _existing_meta.update(_new_meta)
            _meta_path.write_text(json.dumps(_existing_meta), encoding="utf-8")
        except OSError:
            pass

        # Enable per-session event persistence so that all eventbus events
        # survive server restarts and can be replayed on cold-session resume.
        # Scan the existing event log to find the max iteration ever written,
        # then use max+1 as offset so resumed sessions produce monotonically
        # increasing iteration values — preventing frontend message ID collisions.
        iteration_offset = 0
        last_phase = ""
        events_path = queen_dir / "events.jsonl"
        try:
            if events_path.exists():
                max_iter = -1
                with open(events_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            evt = json.loads(line)
                            data = evt.get("data", {})
                            it = data.get("iteration")
                            if isinstance(it, int) and it > max_iter:
                                max_iter = it
                            # Track the latest queen phase from QUEEN_PHASE_CHANGED events
                            if evt.get("type") == "queen_phase_changed":
                                phase = data.get("phase")
                                if phase:
                                    last_phase = phase
                        except (json.JSONDecodeError, TypeError):
                            continue
                if max_iter >= 0:
                    iteration_offset = max_iter + 1
                    logger.info(
                        "Session '%s' resuming with iteration_offset=%d"
                        " (from events.jsonl max), last phase: %s",
                        session.id,
                        iteration_offset,
                        last_phase or "unknown",
                    )
        except OSError:
            pass
        session.event_bus.set_session_log(events_path, iteration_offset=iteration_offset)

        logger.debug("[_start_queen] Calling create_queen...")
        session.queen_task = await create_queen(
            session=session,
            session_manager=self,
            worker_identity=worker_identity,
            queen_dir=queen_dir,
            initial_prompt=initial_prompt,
        )
        logger.debug("[_start_queen] create_queen returned, queen_task=%s, queen_executor=%s", session.queen_task, session.queen_executor)

        # Auto-load worker on cold restore — the queen's conversation expects
        # the agent to be loaded, but the new session has no worker.
        if session.queen_resume_from and not session.graph_runtime:
            meta_path = queen_dir / "meta.json"
            if meta_path.exists():
                try:
                    _meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    _agent_path = _meta.get("agent_path")
                    _phase = _meta.get("phase")

                    if _agent_path and Path(_agent_path).exists():
                        if _phase in ("staging", "running", None):
                            # Agent fully built — load worker and resume
                            await self.load_graph(session.id, _agent_path)
                            if session.phase_state:
                                await session.phase_state.switch_to_staging(source="auto")
                            # Emit flowchart overlay so frontend can display it
                            await self._emit_flowchart_on_restore(session, _agent_path)
                            logger.info("Cold restore: auto-loaded worker from %s", _agent_path)
                        elif _phase == "building":
                            # Agent folder exists but incomplete — resume building
                            if session.phase_state:
                                session.phase_state.agent_path = _agent_path
                                await session.phase_state.switch_to_building(source="auto")
                            logger.info("Cold restore: resumed BUILDING phase for %s", _agent_path)
                        elif _phase == "planning":
                            if session.phase_state:
                                session.phase_state.agent_path = _agent_path
                            logger.info("Cold restore: PLANNING phase for %s", _agent_path)
                except Exception:
                    logger.warning("Cold restore: failed to auto-load worker", exc_info=True)

        # Memory reflection/recall subscriptions are set up inside
        # queen_orchestrator.create_queen() → _queen_loop() and stored
        # on session.memory_reflection_subs for teardown.

    # ------------------------------------------------------------------
    # Queen notifications
    # ------------------------------------------------------------------

    async def _notify_queen_graph_loaded(self, session: Session) -> None:
        """Inject a system message into the queen about the loaded graph."""
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        executor = session.queen_executor
        if executor is None:
            return
        node = executor.node_registry.get("queen")
        if node is None or not hasattr(node, "inject_event"):
            return

        profile = build_worker_profile(session.graph_runtime, agent_path=session.worker_path)

        # Append available trigger info so the queen knows what's schedulable
        trigger_lines = ""
        if session.available_triggers:
            parts = []
            for t in session.available_triggers.values():
                cfg = t.trigger_config
                detail = cfg.get("cron") or f"every {cfg.get('interval_minutes', '?')} min"
                task_info = f' -> task: "{t.task}"' if t.task else " (no task configured)"
                parts.append(f"  - {t.id} ({t.trigger_type}: {detail}){task_info}")
            trigger_lines = (
                "\n\nAvailable triggers (inactive — use set_trigger to activate):\n"
                + "\n".join(parts)
            )

        await node.inject_event(f"[SYSTEM] Graph loaded.{profile}{trigger_lines}")

    async def _emit_graph_loaded(self, session: Session) -> None:
        """Publish a WORKER_GRAPH_LOADED event so the frontend can update."""
        from framework.runtime.event_bus import AgentEvent, EventType

        info = session.worker_info
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.WORKER_GRAPH_LOADED,
                stream_id="queen",
                data={
                    "graph_id": session.graph_id,
                    "graph_name": info.name if info else session.graph_id,
                    "agent_path": str(session.worker_path) if session.worker_path else "",
                    "goal": info.goal_name if info else "",
                    "node_count": info.node_count if info else 0,
                },
            )
        )

    async def _emit_flowchart_on_restore(self, session: Session, agent_path: str | Path) -> None:
        """Emit FLOWCHART_MAP_UPDATED from persisted flowchart file on cold restore."""
        from framework.runtime.event_bus import AgentEvent, EventType
        from framework.tools.flowchart_utils import load_flowchart_file

        original_draft, flowchart_map = load_flowchart_file(agent_path)
        if original_draft is None:
            return
        # Cache in phase_state so the REST endpoint also returns it
        if session.phase_state:
            session.phase_state.original_draft_graph = original_draft
            session.phase_state.flowchart_map = flowchart_map
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.FLOWCHART_MAP_UPDATED,
                stream_id="queen",
                data={
                    "map": flowchart_map,
                    "original_draft": original_draft,
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
            "Design or build the agent to solve the user's problem "
            "according to your current phase."
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
        # Resolve graph entry node for trigger target
        runner = getattr(session, "runner", None)
        graph_entry = runner.graph.entry_node if runner else None

        for t in triggers.values():
            await session.event_bus.publish(
                AgentEvent(
                    type=event_type,
                    stream_id="queen",
                    data={
                        "trigger_id": t.id,
                        "trigger_type": t.trigger_type,
                        "trigger_config": t.trigger_config,
                        "name": t.description or t.id,
                        **({"entry_node": graph_entry} if graph_entry else {}),
                    },
                )
            )

    async def revive_queen(self, session: Session) -> None:
        """Revive a dead queen executor on an existing session.

        Restarts the queen with the same session context (worker profile, tools, etc.).
        """
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        logger.debug("[revive_queen] Starting revival for session '%s', current queen_executor=%s", session.id, session.queen_executor)

        # Build worker identity if worker is loaded
        worker_identity = (
            build_worker_profile(session.graph_runtime, agent_path=session.worker_path)
            if session.graph_runtime
            else None
        )
        logger.debug("[revive_queen] worker_identity=%s", "present" if worker_identity else "None")

        # Start queen with existing session context
        logger.debug("[revive_queen] Calling _start_queen...")
        await self._start_queen(
            session, worker_identity=worker_identity
        )

        logger.info("Queen revived for session '%s', new queen_executor=%s", session.id, session.queen_executor)

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_session_by_graph_id(self, graph_id: str) -> Session | None:
        """Find a session by its loaded graph's ID."""
        for s in self._sessions.values():
            if s.graph_id == graph_id:
                return s
        return None

    def get_session_for_agent(self, agent_id: str) -> Session | None:
        """Resolve an agent_id to a session (backward compat).

        Checks session.id first, then session.graph_id.
        """
        s = self._sessions.get(agent_id)
        if s:
            return s
        return self.get_session_by_graph_id(agent_id)

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
            # Flat layout: conversations/parts/*.json
            flat_parts = convs_dir / "parts"
            if flat_parts.exists() and any(f.suffix == ".json" for f in flat_parts.iterdir()):
                has_messages = True
            else:
                # Node-based layout: conversations/<node_id>/parts/*.json
                for node_dir in convs_dir.iterdir():
                    if not node_dir.is_dir() or node_dir.name == "parts":
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

                    def _collect_parts(parts_dir: Path, _dest: list[dict] = all_parts) -> None:
                        if not parts_dir.exists():
                            return
                        for part_file in sorted(parts_dir.iterdir()):
                            if part_file.suffix != ".json":
                                continue
                            try:
                                part = json.loads(part_file.read_text(encoding="utf-8"))
                                part.setdefault("created_at", part_file.stat().st_mtime)
                                _dest.append(part)
                            except (json.JSONDecodeError, OSError):
                                continue

                    # Flat layout: conversations/parts/*.json
                    _collect_parts(convs_dir / "parts")
                    # Node-based layout: conversations/<node_id>/parts/*.json
                    for node_dir in convs_dir.iterdir():
                        if not node_dir.is_dir() or node_dir.name == "parts":
                            continue
                        _collect_parts(node_dir / "parts")
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
