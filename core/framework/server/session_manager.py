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
from typing import Any, Literal

from framework.config import QUEENS_DIR
from framework.host.triggers import TriggerDefinition

logger = logging.getLogger(__name__)


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"session_{ts}_{uuid.uuid4().hex[:8]}"


def _queen_session_dir(session_id: str, queen_name: str = "default") -> Path:
    """Return the on-disk directory for a queen session."""
    return QUEENS_DIR / queen_name / "sessions" / session_id


def _find_queen_session_dir(session_id: str) -> Path:
    """Search all queen directories for a session. Falls back to default."""
    if QUEENS_DIR.exists():
        for queen_dir in QUEENS_DIR.iterdir():
            if not queen_dir.is_dir():
                continue
            candidate = queen_dir / "sessions" / session_id
            if candidate.exists():
                return candidate
    return _queen_session_dir(session_id)


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
    # Loaded colony (optional)
    colony_id: str | None = None
    worker_path: Path | None = None
    runner: Any | None = None  # AgentRunner
    colony_runtime: Any | None = None  # legacy worker AgentRuntime (Phase 2 deprecation pending)
    # Phase 2 unified runtime: a real ColonyRuntime hosting the queen as
    # overseer and (in colony sessions) parallel workers spawned via
    # run_parallel_workers. Always set once _start_queen has run.
    colony: Any | None = None  # ColonyRuntime
    worker_info: Any | None = None  # AgentInfo
    # Queen phase state (working/reviewing)
    phase_state: Any = None  # QueenPhaseState
    # Worker handoff subscription (colony-scoped escalation receiver)
    worker_handoff_sub: str | None = None
    # Pending worker escalations awaiting queen reply.
    # Keyed by request_id -> {worker_id, colony_id, reason, context, opened_at}.
    # Populated by queen_orchestrator._on_worker_escalation and drained by
    # the reply_to_worker tool.
    pending_escalations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Memory reflection + recall subscriptions (global memory)
    memory_reflection_subs: list = field(default_factory=list)  # list[str]
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
    # Per-trigger fire stats (session lifetime): {trigger_id: {"fire_count": int, "last_fired_at": epoch_ms}}.
    # Reset on process restart — good enough as a "since this session started" counter.
    trigger_fire_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Session directory resumption:
    # When set, _start_queen writes queen conversations to this existing session's
    # directory instead of creating a new one.  This lets cold-restores accumulate
    # all messages in the original session folder so history is never fragmented.
    queen_resume_from: str | None = None
    # Queen session directory (set during _start_queen, used for shutdown reflection)
    queen_dir: Path | None = None
    # Multi-queen support: which queen profile this session uses
    queen_name: str = "default"
    # Colony name: set when a worker is loaded from a colony
    colony_name: str | None = None
    # Session mode discriminator. "dm" = queen DM session under
    # ~/.hive/agents/queens/{queen_id}/sessions/. "colony" = forked colony
    # session under ~/.hive/colonies/{colony_name}/sessions/, with the
    # queen running as the colony's overseer and the run_parallel_workers
    # tool unlocked. The mode is the canonical discriminator for storage
    # path, tool exposure, and SSE filtering — see the Phase 2 plan.
    mode: Literal["dm", "colony"] = "dm"
    # Set to True after the user clicks the COLONY_CREATED system message
    # in this DM. Locks the chat input — the user must compact+fork into a
    # fresh session before continuing the conversation. Persisted in
    # meta.json so the lock survives server restarts.
    colony_spawned: bool = False
    spawned_colony_name: str | None = None


class SessionManager:
    """Manages session lifecycles.

    Thread-safe via asyncio.Lock. Workers are loaded via run_in_executor
    (blocking I/O) then started on the event loop.
    """

    def __init__(self, model: str | None = None, credential_store=None, queen_tool_registry=None) -> None:
        self._sessions: dict[str, Session] = {}
        self._loading: set[str] = set()
        self._model = model
        self._credential_store = credential_store
        self._queen_tool_registry = queen_tool_registry
        self._lock = asyncio.Lock()
        # Strong references for fire-and-forget background tasks (e.g. shutdown
        # reflections) so they aren't garbage-collected before completion.
        self._background_tasks: set[asyncio.Task] = set()

        # Run one-time v2 directory structure migration
        from framework.storage.migrate_v2 import run_migration

        try:
            run_migration()
        except Exception:
            logger.warning("v2 migration failed (non-fatal)", exc_info=True)

        # Ensure every existing colony has an up-to-date progress.db
        # (schema v1, WAL mode) and reclaim any stale claims left behind
        # by crashed workers from the previous run.  Idempotent and
        # fast; runs synchronously because the event loop hasn't
        # started yet at __init__ time.
        from framework.host.progress_db import ensure_all_colony_dbs

        try:
            ensured = ensure_all_colony_dbs()
            if ensured:
                logger.info("progress_db: ensured %d colony DB(s) at startup", len(ensured))
        except Exception:
            logger.warning("progress_db: backfill at startup failed (non-fatal)", exc_info=True)

    def build_llm(self, model: str | None = None):
        """Construct an LLM provider using the server's configured defaults."""
        from framework.config import RuntimeConfig, get_hive_config

        rc = RuntimeConfig(model=model or self._model or RuntimeConfig().model)
        llm_config = get_hive_config().get("llm", {})
        if llm_config.get("use_antigravity_subscription"):
            from framework.llm.antigravity import AntigravityProvider

            return AntigravityProvider(model=rc.model)

        from framework.llm.litellm import LiteLLMProvider

        return LiteLLMProvider(
            model=rc.model,
            api_key=rc.api_key,
            api_base=rc.api_base,
            **rc.extra_kwargs,
        )

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def _create_session_core(
        self,
        session_id: str | None = None,
        model: str | None = None,
    ) -> Session:
        """Create session infrastructure (EventBus, LLM) without starting queen.

        Internal helper — use create_session() or create_session_with_worker_colony().
        """
        from framework.host.event_bus import EventBus

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        resolved_id = session_id or f"session_{ts}_{uuid.uuid4().hex[:8]}"

        async with self._lock:
            if resolved_id in self._sessions:
                raise ValueError(f"Session '{resolved_id}' already exists")

        # Session owns these — shared with queen and worker
        llm = self.build_llm(model=model)
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

    def _resume_queen_name(self, session_id: str) -> str | None:
        """Best-effort queen identity lookup for a persisted session."""
        session_dir = _find_queen_session_dir(session_id)
        if not session_dir.exists():
            return None

        meta_path = session_dir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
            queen_id = meta.get("queen_id")
            if isinstance(queen_id, str) and queen_id.strip():
                return queen_id.strip()

        if session_dir.parent.name == "sessions":
            queen_id = session_dir.parent.parent.name
            if queen_id:
                return queen_id
        return None

    async def _ensure_session_queen_identity(
        self,
        session: Session,
        initial_prompt: str | None = None,
    ) -> dict:
        """Resolve the queen identity and return the loaded profile.

        Sets ``session.queen_name`` and returns the validated profile dict.
        The caller can pass the profile directly to the orchestrator without
        re-loading from disk.
        """
        from framework.agents.queen.queen_profiles import (
            ensure_default_queens,
            load_queen_profile,
            select_queen,
        )

        ensure_default_queens()

        candidates: list[str] = []
        current_queen = (session.queen_name or "").strip()
        if current_queen and current_queen != "default":
            candidates.append(current_queen)

        if session.queen_resume_from:
            resumed_queen = self._resume_queen_name(session.queen_resume_from)
            if resumed_queen and resumed_queen not in candidates:
                candidates.append(resumed_queen)

        for queen_id in candidates:
            try:
                profile = load_queen_profile(queen_id)
            except FileNotFoundError:
                logger.warning("Session '%s': queen profile '%s' not found", session.id, queen_id)
                continue
            session.queen_name = queen_id
            return profile

        selector_input = initial_prompt or ""
        queen_id = await select_queen(selector_input, session.llm)
        session.queen_name = queen_id
        return load_queen_profile(queen_id)

    async def create_session(
        self,
        session_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
        queen_name: str | None = None,
        initial_phase: str | None = None,
    ) -> Session:
        """Create a new session with a queen but no worker.

        When ``queen_resume_from`` is set the queen writes conversation messages
        to that existing session's directory instead of creating a new one.
        This preserves full conversation history across server restarts.

        When ``queen_name`` is set the session is pre-bound to that queen
        identity, skipping LLM auto-selection in the identity hook.
        """
        # Reuse the original session ID when cold-restoring
        resolved_session_id = queen_resume_from or session_id
        session = await self._create_session_core(session_id=resolved_session_id, model=model)
        session.queen_resume_from = queen_resume_from
        if queen_name:
            session.queen_name = queen_name

        # Start queen immediately (queen-only, no worker tools yet)
        await self._start_queen(
            session,
            worker_identity=None,
            initial_prompt=initial_prompt,
            initial_phase=initial_phase,
        )

        logger.info(
            "Session '%s' created (queen-only, resume_from=%s)",
            session.id,
            queen_resume_from,
        )
        return session

    async def create_session_with_worker_colony(
        self,
        agent_path: str | Path,
        agent_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
        queen_name: str | None = None,
        initial_phase: str | None = None,
        worker_name: str | None = None,
    ) -> Session:
        """Create a session and load a worker in one step.

        When ``worker_name`` is provided, creates a worker-only session
        (no queen) — the worker runs as the primary interactive loop.
        Otherwise, creates a queen+worker session (legacy path).
        """
        agent_path = Path(agent_path)
        resolved_colony_id = agent_id or agent_path.name

        if worker_name:
            return await self._create_worker_only_session(
                agent_path=agent_path,
                worker_name=worker_name,
                colony_id=resolved_colony_id,
                session_id=session_id,
                model=model,
                initial_prompt=initial_prompt,
                queen_resume_from=queen_resume_from,
                queen_name=queen_name,
            )

        from framework.tools.queen_lifecycle_tools import build_worker_profile

        agent_path = Path(agent_path)
        resolved_colony_id = agent_id or agent_path.name

        # Read colony metadata.json for queen provenance (queen_name,
        # queen_session_id) so we can restore the correct queen identity
        # and resume from the originating session when no explicit
        # queen_resume_from was provided.
        _colony_metadata: dict = {}
        _colony_metadata_path = agent_path / "metadata.json"
        if _colony_metadata_path.exists():
            try:
                _colony_metadata = json.loads(_colony_metadata_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        if not queen_name:
            queen_name = _colony_metadata.get("queen_name") or None

        # Colony metadata's queen_session_id is the authoritative session
        # for this colony (the forked session).  It takes priority over
        # whatever the frontend found via history scan, which may be the
        # source session instead of the fork.
        _colony_session_id = _colony_metadata.get("queen_session_id")
        if _colony_session_id:
            queen_resume_from = _colony_session_id
        elif not queen_resume_from:
            queen_resume_from = None

        # When cold-restoring, check meta.json for the phase — if the agent
        # was still being built we must NOT try to load the worker (the code
        # is incomplete and will fail to import).
        _resume_queen_id: str | None = None
        if queen_resume_from:
            _resume_phase = None
            _meta_path = _find_queen_session_dir(queen_resume_from) / "meta.json"
            if _meta_path.exists():
                try:
                    _meta = json.loads(_meta_path.read_text(encoding="utf-8"))
                    _resume_phase = _meta.get("phase")
                    _resume_queen_id = _meta.get("queen_id")
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
                    queen_name=queen_name or _resume_queen_id,
                )

        # Use the colony's forked session ID as the live session ID.
        # If it's already live (user navigated back), return it directly
        # -- but only if it belongs to this colony.
        if queen_resume_from and queen_resume_from in self._sessions:
            existing = self._sessions[queen_resume_from]
            if existing.worker_path and str(existing.worker_path) == str(agent_path):
                return existing

        # When the queen forked this colony, the inherited DM transcript
        # is compacted in the background (see fork_session_into_colony).
        # Block here until that compactor finishes so _load_worker_core
        # reads the compacted summary — not the raw transcript (which
        # would defeat the fork's purpose). Bounded wait: on timeout we
        # proceed anyway so a stuck compactor can't brick the colony.
        if queen_resume_from:
            try:
                from framework.server import compaction_status

                await compaction_status.await_completion(
                    _find_queen_session_dir(queen_resume_from),
                    timeout=180.0,
                )
            except Exception:
                logger.debug(
                    "await_compaction failed for %s — proceeding",
                    queen_resume_from,
                    exc_info=True,
                )

        session = await self._create_session_core(
            session_id=_colony_session_id or queen_resume_from,
            model=model,
        )
        session.queen_resume_from = queen_resume_from
        if queen_name:
            session.queen_name = queen_name
        elif _resume_queen_id:
            session.queen_name = _resume_queen_id
        try:
            # Load the colony FIRST (before queen) so queen gets full tools
            await self._load_worker_core(
                session,
                agent_path,
                colony_id=resolved_colony_id,
                model=model,
            )

            # Restore active triggers from persisted state (cold restore)
            await self._restore_active_triggers(session, session.id)

            # Start queen with worker profile + lifecycle + monitoring tools
            worker_identity = (
                build_worker_profile(session.colony_runtime, agent_path=agent_path) if session.colony_runtime else None
            )
            await self._start_queen(
                session,
                worker_identity=worker_identity,
                initial_prompt=initial_prompt,
                initial_phase=initial_phase,
            )

        except Exception:
            if queen_resume_from:
                # Cold restore: worker load failed (e.g. incomplete code from a
                # building session, or the colony directory was deleted). Fall
                # back to queen-only so the user can continue the conversation.
                # Forward queen_name so the recovered session is stored under
                # the correct queen identity -- otherwise it lands in default/
                # and the frontend routes the user to the wrong dir.
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
                    queen_name=queen_name or _resume_queen_id,
                )
            # If anything fails (non-cold-restore), tear down the session
            await self.stop_session(session.id)
            raise
        return session

    async def _create_worker_only_session(
        self,
        agent_path: Path,
        worker_name: str,
        colony_id: str,
        session_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
        queen_name: str | None = None,
    ) -> Session:
        """Create a worker-only session (no queen).

        Loads the worker's {worker_name}.json config, creates an AgentLoop,
        and sets it as the primary interactive executor so chat/SSE work
        through the existing infrastructure.
        """
        import json as _json
        import shutil

        from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
        from framework.agent_loop.types import AgentContext, AgentSpec
        from framework.orchestrator.graph_executor import GraphExecutor
        from framework.schemas.goal import Goal
        from framework.storage.conversation_store import FileConversationStore
        from framework.tracker.decision_tracker import DecisionTracker

        worker_config_path = agent_path / f"{worker_name}.json"
        if not worker_config_path.exists():
            raise FileNotFoundError(f"Worker config not found: {worker_config_path}")

        worker_data = _json.loads(worker_config_path.read_text(encoding="utf-8"))

        session = await self._create_session_core(
            session_id=queen_resume_from,
            model=model,
        )
        session.queen_resume_from = queen_resume_from
        if queen_name:
            session.queen_name = queen_name

        session.colony_id = colony_id
        session.colony_name = colony_id
        session.worker_path = agent_path

        # Worker storage: ~/.hive/agents/{colony_name}/{worker_name}/
        worker_storage = Path.home() / ".hive" / "agents" / colony_id / worker_name
        worker_storage.mkdir(parents=True, exist_ok=True)

        # Copy conversations from colony if fresh
        worker_conv_dir = worker_storage / "conversations"
        if not worker_conv_dir.exists():
            colony_conv = agent_path / "conversations"
            if colony_conv.exists():
                shutil.copytree(colony_conv, worker_conv_dir)
        conversation_store = FileConversationStore(worker_conv_dir)

        # Build AgentSpec from worker config
        spec = AgentSpec(
            id=worker_name,
            name=worker_data.get("name", worker_name),
            description=worker_data.get("description", ""),
            system_prompt=worker_data.get("system_prompt", ""),
            tools=worker_data.get("tools", []),
            tool_access_policy="all",
            identity_prompt=worker_data.get("identity_prompt", ""),
        )

        # Build loop config
        lc_data = worker_data.get("loop_config", {})
        loop_config = LoopConfig(
            max_iterations=lc_data.get("max_iterations", 999_999),
            max_tool_calls_per_turn=lc_data.get("max_tool_calls_per_turn", 30),
            max_context_tokens=lc_data.get("max_context_tokens", 180_000),
            spillover_dir=str(agent_path / "data"),
        )

        # Build goal
        goal_data = worker_data.get("goal", {})
        goal = Goal(
            id=f"{colony_id}-{worker_name}",
            name=goal_data.get("description", worker_name)[:60],
            description=goal_data.get("description", ""),
        )

        # Queen dir for SSE/session metadata (reuse queen session storage)
        storage_session_id = queen_resume_from or session.id
        queen_dir = _queen_session_dir(storage_session_id, session.queen_name)
        queen_dir.mkdir(parents=True, exist_ok=True)
        session.queen_dir = queen_dir

        # Write meta
        _meta_path = queen_dir / "meta.json"
        _existing_meta: dict = {}
        if _meta_path.exists():
            try:
                _existing_meta = _json.loads(_meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        _existing_meta.update(
            {
                "created_at": time.time(),
                "queen_id": session.queen_name,
                "agent_name": worker_name,
                "agent_path": str(agent_path),
                "worker_name": worker_name,
            }
        )
        _meta_path.write_text(_json.dumps(_existing_meta), encoding="utf-8")

        # Set up event log
        iteration_offset = 0
        events_path = queen_dir / "events.jsonl"
        if events_path.exists():
            max_iter = -1
            with open(events_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        evt = _json.loads(line)
                        i = evt.get("iteration", 0)
                        if i > max_iter:
                            max_iter = i
                    except Exception:
                        pass
            if max_iter >= 0:
                iteration_offset = max_iter + 1

        # Load the worker via AgentLoader to get the full pipeline (MCP, skills, creds)
        from framework.loader import AgentLoader

        loop = asyncio.get_running_loop()
        runner = await loop.run_in_executor(
            None,
            lambda: AgentLoader.load(
                agent_path,
                model=model or self._model,
                interactive=False,
                skip_credential_validation=True,
                credential_store=self._credential_store,
            ),
        )
        if runner._agent_runtime is None:
            await loop.run_in_executor(
                None,
                lambda: runner._setup(event_bus=session.event_bus),
            )

        session.colony_runtime = runner._agent_runtime
        session.runner = runner

        # Start the AgentHost
        runtime = runner._agent_runtime
        if runtime and not runtime.is_running:
            await runtime.start()

        # Register entry point so we can trigger execution
        from framework.host.execution_manager import EntryPointSpec

        if not runtime._streams:
            runtime.register_entry_point(
                EntryPointSpec(
                    id="default",
                    name="Default",
                    entry_node=worker_name,
                    trigger_type="manual",
                    isolation_level="shared",
                ),
            )

        # Create a queen-like executor for the worker so chat injection works
        # We reuse the queen_executor field even though it's a worker
        queen_registry = runner._tool_registry

        # Start with queen's default tools if available
        queen_llm = runner._llm or session.llm
        all_tools = list(queen_registry.get_tools().values())
        tool_executor = queen_registry.get_executor()

        agent_loop = AgentLoop(
            event_bus=session.event_bus,
            config=loop_config,
            tool_executor=tool_executor,
            conversation_store=conversation_store,
        )

        worker_ctx = AgentContext(
            runtime=DecisionTracker(worker_storage),
            agent_id=worker_name,
            agent_spec=spec,
            input_data={"task": goal_data.get("description", "")},
            llm=queen_llm,
            available_tools=all_tools,
            goal_context=goal.to_prompt_context(),
            goal=goal,
            max_tokens=8192,
            stream_id=worker_name,
            execution_id=worker_name,
            identity_prompt=worker_data.get("identity_prompt", ""),
            memory_prompt=worker_data.get("memory_prompt", ""),
            skills_catalog_prompt=worker_data.get("skills_catalog_prompt", ""),
            protocols_prompt=worker_data.get("protocols_prompt", ""),
            skill_dirs=worker_data.get("skill_dirs", []),
        )

        session.queen_executor = GraphExecutor(
            node_id=worker_name,
            agent_loop=agent_loop,
            context=worker_ctx,
            event_bus=session.event_bus,
        )

        # Start the worker's agent loop in the background.
        # Scope browser profile per-session so parallel sessions drive
        # independent Chrome tab groups. Browser tools live in an MCP
        # subprocess; we inject `profile` via the ToolRegistry execution
        # context (a CONTEXT_PARAM) so it flows into every tool call.
        async def _run_worker():
            try:
                from framework.loader.tool_registry import ToolRegistry

                ToolRegistry.set_execution_context(profile=session.id)
            except Exception:
                logger.debug("Worker: failed to set browser profile", exc_info=True)
            await session.queen_executor.run(initial_message=initial_prompt)

        session.queen_task = asyncio.create_task(_run_worker())

        # Set up event persistence
        if session.event_bus and queen_dir:
            session.event_bus.start_persistence(queen_dir, iteration_offset=iteration_offset)

        logger.info(
            "Worker-only session '%s' started: colony=%s worker=%s tools=%d",
            session.id,
            colony_id,
            worker_name,
            len(all_tools),
        )

        async with self._lock:
            self._loading.discard(session.id)

        return session

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    async def _load_worker_core(
        self,
        session: Session,
        agent_path: str | Path,
        colony_id: str | None = None,
        model: str | None = None,
    ) -> None:
        """Load a worker into a session (core logic).

        Sets up the runner, runtime, and session fields. Does NOT notify
        the queen — callers handle that step.
        """
        from framework.loader import AgentLoader

        agent_path = Path(agent_path)
        resolved_colony_id = colony_id or agent_path.name

        if session.colony_runtime is not None:
            raise ValueError(f"Session '{session.id}' already has colony '{session.colony_id}'")

        async with self._lock:
            if session.id in self._loading:
                raise ValueError(f"Session '{session.id}' is currently loading a colony")
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
                lambda: AgentLoader.load(
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

            # Load triggers from the agent's triggers.json definition file.
            # triggers.json is written exclusively by set_trigger, so the
            # presence of an entry means the user explicitly activated this
            # trigger in a previous session. We treat the file as the
            # source of truth and auto-start each trigger on colony load
            # so the user doesn't have to re-activate after every restart.
            # The per-session active_triggers tracking still functions, but
            # is no longer the only path to "running" status.
            from framework.tools.queen_lifecycle_tools import (
                _read_agent_triggers_json,
                _start_trigger_timer,
                _start_trigger_webhook,
            )

            triggers_to_autostart: list[str] = []
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
                    triggers_to_autostart.append(tid)
                    logger.info("Loaded trigger '%s' (%s) from triggers.json", tid, ttype)

            # Auto-start every trigger discovered in triggers.json. The
            # frontend listens for TRIGGER_ACTIVATED to render the active
            # state; per-session active_triggers tracking still happens
            # via _persist_active_triggers below.
            for tid in triggers_to_autostart:
                tdef = session.available_triggers[tid]
                try:
                    if tdef.trigger_type == "timer":
                        await _start_trigger_timer(session, tid, tdef)
                    elif tdef.trigger_type == "webhook":
                        await _start_trigger_webhook(session, tid, tdef)
                    tdef.active = True
                    session.active_trigger_ids.add(tid)
                    logger.info("Auto-started trigger '%s' on colony load", tid)
                except Exception:
                    logger.warning(
                        "Failed to auto-start trigger '%s' on colony load",
                        tid,
                        exc_info=True,
                    )

            if session.active_trigger_ids:
                # Persist the auto-started set so a subsequent restart
                # finds them in state.active_triggers and the existing
                # _restore_active_triggers path also keeps working.
                from framework.tools.queen_lifecycle_tools import (
                    _persist_active_triggers,
                )

                await _persist_active_triggers(session, session.id)

            if session.available_triggers:
                # Emit AVAILABLE for every trigger (so the UI knows the
                # definition exists) and ACTIVATED for the ones we just
                # auto-started. The frontend handler treats them as the
                # same case and uses the latter to flip the card to
                # active.
                await self._emit_trigger_events(session, "available", session.available_triggers)
                if session.active_trigger_ids:
                    activated = {
                        tid: session.available_triggers[tid]
                        for tid in session.active_trigger_ids
                        if tid in session.available_triggers
                    }
                    if activated:
                        await self._emit_trigger_events(session, "activated", activated)

            # Start runtime on event loop
            if runtime and not runtime.is_running:
                await runtime.start()

            # Clean up stale "active" sessions from previous (dead) processes
            self._cleanup_stale_active_sessions(agent_path)

            info = runner.info()

            # Update session
            session.colony_id = resolved_colony_id
            session.worker_path = agent_path
            session.runner = runner
            session.colony_runtime = runtime
            session.worker_info = info

            async with self._lock:
                self._loading.discard(session.id)

            logger.info(
                "Worker '%s' loaded into session '%s'",
                resolved_colony_id,
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
                logger.info("Marked stale session '%s' as cancelled for agent '%s'", d.name, agent_path.name)
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
        if not session.available_triggers or not session.colony_runtime:
            return
        try:
            store = session.colony_runtime._session_store
            state = await store.read_state(session_id)
            if state and state.active_triggers:
                from framework.host.event_bus import AgentEvent, EventType
                from framework.tools.queen_lifecycle_tools import (
                    _start_trigger_timer,
                    _start_trigger_webhook,
                )

                runner = getattr(session, "runner", None)
                colony_entry = runner.graph.entry_node if runner else None
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
                        # Emit TRIGGER_ACTIVATED so the frontend knows this
                        # trigger is running after a server restart. Without
                        # this, the previously-available event is the only
                        # signal the UI ever gets, and the trigger appears
                        # inactive forever.
                        if session.event_bus:
                            await session.event_bus.publish(
                                AgentEvent(
                                    type=EventType.TRIGGER_ACTIVATED,
                                    stream_id="queen",
                                    data={
                                        "trigger_id": tdef.id,
                                        "trigger_type": tdef.trigger_type,
                                        "trigger_config": tdef.trigger_config,
                                        "name": tdef.description or tdef.id,
                                        **({"entry_node": colony_entry} if colony_entry else {}),
                                    },
                                )
                            )
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

    async def load_colony(
        self,
        session_id: str,
        agent_path: str | Path,
        colony_id: str | None = None,
        model: str | None = None,
    ) -> Session:
        """Load a worker colony into an existing session (with running queen).

        Starts the colony runtime and notifies the queen.
        """
        agent_path = Path(agent_path)

        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")

        await self._load_worker_core(
            session,
            agent_path,
            colony_id=colony_id,
            model=model,
        )

        # Notify queen about the loaded worker (skip for queen itself).
        if agent_path.name != "queen" and session.colony_runtime:
            await self._notify_queen_colony_loaded(session)

        # Update meta.json so cold-restore can discover this session by agent_path
        storage_session_id = session.queen_resume_from or session.id
        meta_path = _queen_session_dir(storage_session_id, session.queen_name) / "meta.json"
        try:
            _agent_name = (
                session.worker_info.name if session.worker_info else str(agent_path.name).replace("_", " ").title()
            )
            existing_meta = {}
            if meta_path.exists():
                existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_meta["agent_name"] = _agent_name
            existing_meta["agent_path"] = str(session.worker_path) if session.worker_path else str(agent_path)
            meta_path.write_text(json.dumps(existing_meta), encoding="utf-8")
        except OSError:
            pass

        await self._restore_active_triggers(session, session_id)

        # Emit SSE event so the frontend can update UI
        await self._emit_colony_loaded(session)

        return session

    async def unload_colony(self, session_id: str) -> bool:
        """Unload the worker colony from a session. Queen stays alive."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.colony_runtime is None:
            return False

        # Cleanup worker
        if session.runner:
            try:
                await session.runner.cleanup_async()
            except Exception as e:
                logger.error("Error cleaning up colony '%s': %s", session.colony_id, e)

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

        colony_id = session.colony_id
        session.colony_id = None
        session.worker_path = None
        session.runner = None
        session.colony_runtime = None
        session.worker_info = None

        # Notify queen
        await self._notify_queen_worker_unloaded(session)

        logger.info("Colony '%s' unloaded from session '%s'", colony_id, session_id)
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

        if session.worker_handoff_sub is not None:
            try:
                session.event_bus.unsubscribe(session.worker_handoff_sub)
            except Exception:
                pass
            session.worker_handoff_sub = None

        # Stop memory reflection/recall subscriptions
        for sub_id in session.memory_reflection_subs:
            try:
                session.event_bus.unsubscribe(sub_id)
            except Exception:
                pass
        session.memory_reflection_subs.clear()

        # Run a final shutdown reflection so recent conversation insights
        # are persisted before the session is destroyed (fire-and-forget).
        if session.queen_dir is not None:
            try:
                from framework.agents.queen.queen_memory_v2 import (
                    global_memory_dir,
                    queen_memory_dir,
                )
                from framework.agents.queen.reflection_agent import run_shutdown_reflection

                global_mem_dir = global_memory_dir()
                queen_mem_dir = queen_memory_dir(session.queen_name)
                if session.phase_state is not None:
                    global_mem_dir = session.phase_state.global_memory_dir or global_mem_dir
                    queen_mem_dir = session.phase_state.queen_memory_dir or queen_mem_dir

                task = asyncio.create_task(
                    asyncio.shield(
                        run_shutdown_reflection(
                            session.queen_dir,
                            session.llm,
                            global_memory_dir_override=global_mem_dir,
                            queen_memory_dir=queen_mem_dir,
                            queen_id=session.queen_name,
                        )
                    ),
                    name=f"shutdown-reflect-{session_id}",
                )
                logger.info("Session '%s': shutdown reflection spawned", session_id)
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except Exception:
                logger.warning("Session '%s': failed to spawn shutdown reflection", session_id, exc_info=True)

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

        # Stop the unified ColonyRuntime (Phase 2 wiring) if it was started
        if session.colony is not None:
            try:
                await session.colony.stop()
            except Exception:
                logger.warning(
                    "Session '%s': error stopping unified ColonyRuntime",
                    session_id,
                    exc_info=True,
                )
            session.colony = None

        # Close per-session event log
        session.event_bus.close_session_log()

        logger.info("Session '%s' stopped", session_id)
        return True

    # ------------------------------------------------------------------
    # Queen startup
    # ------------------------------------------------------------------

    def _subscribe_worker_handoffs(self, session: Session, executor: Any) -> None:
        """Deprecated — colony-scoped escalation routing lives in queen_orchestrator.

        Kept as a shim so any legacy caller is a no-op. The real subscription
        is installed by ``queen_orchestrator.create_queen`` via
        ``colony_runtime.subscribe_to_events(..., filter_colony=...)`` so that
        cross-colony leakage is impossible and every handoff carries the
        worker_id + request_id the queen needs to reply with addressed intent.
        """
        return None

    async def _start_queen(
        self,
        session: Session,
        worker_identity: str | None,
        initial_prompt: str | None = None,
        initial_phase: str | None = None,
    ) -> None:
        """Start the queen executor for a session.

        When ``session.queen_resume_from`` is set, queen conversation messages
        are written to the ORIGINAL session's directory so the full conversation
        history accumulates in one place across server restarts.
        """
        from framework.server.queen_orchestrator import create_queen

        logger.debug(
            "[_start_queen] Starting for session %s, current queen_executor=%s",
            session.id,
            session.queen_executor,
        )

        queen_profile = await self._ensure_session_queen_identity(session, initial_prompt)

        # Determine which session directory to use for queen storage.
        # When queen_resume_from is set we write to the ORIGINAL session's
        # directory so that all messages accumulate in one place.
        storage_session_id = session.queen_resume_from or session.id
        queen_dir = _queen_session_dir(storage_session_id, session.queen_name)
        queen_dir.mkdir(parents=True, exist_ok=True)
        session.queen_dir = queen_dir

        # Always write/update session metadata so history sidebar has correct
        # agent name, path, and last-active timestamp (important so the original
        # session directory sorts as "most recent" after a cold-restore resume).
        _meta_path = queen_dir / "meta.json"
        try:
            _agent_name = (
                session.worker_info.name
                if session.worker_info
                else (str(session.worker_path.name).replace("_", " ").title() if session.worker_path else None)
            )
            # Merge into existing meta.json to preserve fields written by
            # _update_meta_json (e.g. phase, agent_path set during building).
            _existing_meta: dict = {}
            if _meta_path.exists():
                try:
                    _existing_meta = json.loads(_meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            _new_meta: dict = {
                "created_at": time.time(),
                "queen_id": session.queen_name,
            }
            if _agent_name is not None:
                _new_meta["agent_name"] = _agent_name
            if session.worker_path is not None:
                _new_meta["agent_path"] = str(session.worker_path)
            _existing_meta.update(_new_meta)
            _meta_path.write_text(json.dumps(_existing_meta), encoding="utf-8")
            # Hydrate colony-spawned lock state from meta.json so the lock
            # survives server restart / cold-resume into a live session.
            if _existing_meta.get("colony_spawned") is True:
                session.colony_spawned = True
                _spawned_name = _existing_meta.get("spawned_colony_name")
                if isinstance(_spawned_name, str):
                    session.spawned_colony_name = _spawned_name
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
                        "Session '%s' resuming with iteration_offset=%d (from events.jsonl max), last phase: %s",
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
            queen_profile=queen_profile,
            initial_prompt=initial_prompt,
            initial_phase=initial_phase,
            tool_registry=self._queen_tool_registry,
        )
        logger.debug(
            "[_start_queen] create_queen returned, queen_task=%s, queen_executor=%s",
            session.queen_task,
            session.queen_executor,
        )

        # Phase 2 wiring: stand up a real ColonyRuntime that shares the
        # queen's llm, tools, event bus, and storage path. In a DM session
        # it has no parallel workers (the queen runs in queen_task), but
        # the run_parallel_workers tool (Phase 4) will use this runtime
        # as the spawn surface, and worker SUBAGENT_REPORT events flow
        # back through the shared event_bus to the existing SSE.
        try:
            await self._start_unified_colony_runtime(session, queen_dir)
        except Exception:
            # ColonyRuntime is dormant infrastructure today — never let
            # its construction abort queen startup. Phase 4 will harden.
            logger.warning(
                "_start_queen: unified ColonyRuntime construction failed",
                exc_info=True,
            )

        # Auto-load worker on cold restore — the queen's conversation expects
        # the colony to be loaded, but the new session has no worker.
        if session.queen_resume_from and not session.colony_runtime:
            meta_path = queen_dir / "meta.json"
            if meta_path.exists():
                try:
                    _meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    _agent_path = _meta.get("agent_path")

                    if _agent_path and Path(_agent_path).exists():
                        await self.load_colony(session.id, _agent_path)
                        if session.phase_state:
                            # Restored colony session lands in reviewing — the
                            # queen summarises whatever the last run produced
                            # before the user decides what to do next.
                            await session.phase_state.switch_to_reviewing(source="auto")
                        logger.info("Cold restore: auto-loaded colony from %s", _agent_path)
                except Exception:
                    logger.warning("Cold restore: failed to auto-load colony", exc_info=True)

    # ------------------------------------------------------------------
    # Phase 2: unified ColonyRuntime construction
    # ------------------------------------------------------------------

    async def _start_unified_colony_runtime(
        self,
        session: Session,
        queen_dir: Path,
    ) -> None:
        """Build a real ColonyRuntime sharing the queen's resources.

        This is the Phase 2 wiring. The ColonyRuntime is created with:

        - ``llm``  → ``session.llm``
        - ``event_bus`` → ``session.event_bus`` (so worker SUBAGENT_REPORT
          and lifecycle events flow through the same bus the SSE handler
          already subscribes to)
        - ``tools`` → the queen's resolved tool list (stashed by
          ``create_queen`` on ``session._queen_tools``)
        - ``storage_path`` → ``queen_dir``  (parallel workers will land
          under ``{queen_dir}/workers/{worker_id}/`` thanks to
          ``ColonyRuntime.spawn``)
        - ``colony_id`` → ``session.id``

        The runtime is started but no overseer is attached — the queen
        still runs as ``session.queen_task`` from ``create_queen``. This
        is dormant fan-out infrastructure: ``run_parallel_workers``
        (Phase 4) is what activates it.
        """
        from framework.agent_loop.types import AgentSpec
        from framework.host.colony_runtime import ColonyRuntime
        from framework.schemas.goal import Goal

        queen_tools = getattr(session, "_queen_tools", None) or []
        queen_tool_executor = getattr(session, "_queen_tool_executor", None)

        colony_spec = AgentSpec(
            id="queen_colony",
            name="Queen Colony",
            description=(
                "Unified colony runtime hosting the queen overseer and "
                "any parallel workers spawned via run_parallel_workers."
            ),
            system_prompt="",
            tools=[t.name for t in queen_tools],
            tool_access_policy="all",
        )

        colony_goal = Goal(
            id=f"colony_goal_{session.id}",
            name=f"Session {session.id}",
            description="Default goal for the session-level ColonyRuntime.",
        )

        colony = ColonyRuntime(
            agent_spec=colony_spec,
            goal=colony_goal,
            storage_path=queen_dir,
            llm=session.llm,
            tools=queen_tools,
            tool_executor=queen_tool_executor,
            event_bus=session.event_bus,
            colony_id=session.id,
            pipeline_stages=[],  # queen pipeline runs in queen_orchestrator, not here
        )
        await colony.start()
        session.colony = colony

        logger.info(
            "_start_queen: unified ColonyRuntime ready for session %s (%d tools, storage=%s)",
            session.id,
            len(queen_tools),
            queen_dir,
        )

    # ------------------------------------------------------------------
    # Queen notifications
    # ------------------------------------------------------------------

    async def _notify_queen_colony_loaded(self, session: Session) -> None:
        """Inject a system message into the queen about the loaded colony."""
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        executor = session.queen_executor
        if executor is None:
            return
        node = executor.node_registry.get("queen")
        if node is None or not hasattr(node, "inject_event"):
            return

        profile = build_worker_profile(session.colony_runtime, agent_path=session.worker_path)

        # Append available trigger info so the queen knows what's schedulable
        trigger_lines = ""
        if session.available_triggers:
            parts = []
            for t in session.available_triggers.values():
                cfg = t.trigger_config
                detail = cfg.get("cron") or f"every {cfg.get('interval_minutes', '?')} min"
                task_info = f' -> task: "{t.task}"' if t.task else " (no task configured)"
                parts.append(f"  - {t.id} ({t.trigger_type}: {detail}){task_info}")
            trigger_lines = "\n\nAvailable triggers (inactive — use set_trigger to activate):\n" + "\n".join(parts)

        await node.inject_event(f"[SYSTEM] Colony loaded.{profile}{trigger_lines}")

    async def _emit_colony_loaded(self, session: Session) -> None:
        """Publish a WORKER_COLONY_LOADED event so the frontend can update."""
        from framework.host.event_bus import AgentEvent, EventType

        info = session.worker_info
        await session.event_bus.publish(
            AgentEvent(
                type=EventType.WORKER_COLONY_LOADED,
                stream_id="queen",
                data={
                    "colony_id": session.colony_id,
                    "colony_name": info.name if info else session.colony_id,
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
            "Design or build the agent to solve the user's problem "
            "according to your current phase."
        )

    async def _emit_trigger_events(
        self,
        session: Session,
        kind: str,
        triggers: dict[str, TriggerDefinition],
    ) -> None:
        """Emit TRIGGER_AVAILABLE / ACTIVATED / REMOVED events for each trigger."""
        from framework.host.event_bus import AgentEvent, EventType

        if kind == "activated":
            event_type = EventType.TRIGGER_ACTIVATED
        elif kind == "removed":
            event_type = EventType.TRIGGER_REMOVED
        else:
            event_type = EventType.TRIGGER_AVAILABLE
        # Resolve entry node for trigger target
        runner = getattr(session, "runner", None)
        colony_entry = runner.graph.entry_node if runner else None
        fire_times = getattr(session, "trigger_next_fire", {})
        fire_stats = getattr(session, "trigger_fire_stats", {})
        now_mono = time.monotonic()
        now_wall = time.time()

        for t in triggers.values():
            # Merge ephemeral next-fire data + historical fire stats into
            # trigger_config so the UI can render a live-ticking countdown
            # and a "fired Nx · last 2m ago" badge. `next_fire_at` is epoch
            # milliseconds (wall clock) — the frontend anchors its ticker
            # on this. `next_fire_in` is kept for legacy consumers.
            config_out = dict(t.trigger_config)
            mono = fire_times.get(t.id)
            if mono is not None:
                remaining = max(0.0, mono - now_mono)
                config_out["next_fire_in"] = remaining
                config_out["next_fire_at"] = int((now_wall + remaining) * 1000)
            stats = fire_stats.get(t.id)
            if stats:
                config_out["fire_count"] = stats.get("fire_count", 0)
                if stats.get("last_fired_at") is not None:
                    config_out["last_fired_at"] = stats["last_fired_at"]
            await session.event_bus.publish(
                AgentEvent(
                    type=event_type,
                    stream_id="queen",
                    data={
                        "trigger_id": t.id,
                        "trigger_type": t.trigger_type,
                        "trigger_config": config_out,
                        "name": t.description or t.id,
                        **({"entry_node": colony_entry} if colony_entry else {}),
                    },
                )
            )

    async def revive_queen(self, session: Session) -> None:
        """Revive a dead queen executor on an existing session.

        Restarts the queen with the same session context (worker profile, tools, etc.).
        """
        from framework.tools.queen_lifecycle_tools import build_worker_profile

        logger.debug(
            "[revive_queen] Starting revival for session '%s', current queen_executor=%s",
            session.id,
            session.queen_executor,
        )

        # Build worker identity if worker is loaded
        worker_identity = (
            build_worker_profile(session.colony_runtime, agent_path=session.worker_path)
            if session.colony_runtime
            else None
        )
        logger.debug("[revive_queen] worker_identity=%s", "present" if worker_identity else "None")

        # Start queen with existing session context
        logger.debug("[revive_queen] Calling _start_queen...")
        await self._start_queen(session, worker_identity=worker_identity)

        logger.info(
            "Queen revived for session '%s', new queen_executor=%s",
            session.id,
            session.queen_executor,
        )

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def get_session_by_colony_id(self, colony_id: str) -> Session | None:
        """Find a session by its loaded colony's ID."""
        for s in self._sessions.values():
            if s.colony_id == colony_id:
                return s
        return None

    def get_session_for_agent(self, agent_id: str) -> Session | None:
        """Resolve an agent_id to a session (backward compat).

        Checks session.id first, then session.colony_id.
        """
        s = self._sessions.get(agent_id)
        if s:
            return s
        return self.get_session_by_colony_id(agent_id)

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
        ~/.hive/agents/queens/{name}/sessions/{session_id}/conversations/.  Returns None when
        no data is found so callers can fall through to a 404.
        """
        queen_dir = _find_queen_session_dir(session_id)
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
        colony_spawned: bool = False
        spawned_colony_name: str | None = None
        meta_path = queen_dir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agent_name = meta.get("agent_name")
                agent_path = meta.get("agent_path")
                created_at = meta.get("created_at") or created_at
                colony_spawned = bool(meta.get("colony_spawned"))
                _spawned = meta.get("spawned_colony_name")
                if isinstance(_spawned, str):
                    spawned_colony_name = _spawned
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
            "colony_spawned": colony_spawned,
            "spawned_colony_name": spawned_colony_name,
        }

    @staticmethod
    def list_cold_sessions() -> list[dict]:
        """Return metadata for every queen session directory on disk, newest first."""
        if not QUEENS_DIR.exists():
            return []

        # Collect session dirs from all queen identities
        all_session_dirs: list[Path] = []
        try:
            for queen_dir in QUEENS_DIR.iterdir():
                if not queen_dir.is_dir():
                    continue
                sessions_dir = queen_dir / "sessions"
                if sessions_dir.exists():
                    for d in sessions_dir.iterdir():
                        if d.is_dir():
                            all_session_dirs.append(d)
        except OSError:
            return []

        results: list[dict] = []
        for d in all_session_dirs:
            if not d.is_dir():
                continue
            try:
                created_at = d.stat().st_ctime
            except OSError:
                created_at = 0.0
            agent_name: str | None = None
            agent_path: str | None = None
            meta_path = d / "meta.json"
            meta: dict = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    agent_name = meta.get("agent_name")
                    agent_path = meta.get("agent_path")
                    created_at = meta.get("created_at") or created_at
                except (json.JSONDecodeError, OSError):
                    pass

            # Skip colony-forked sessions -- these belong to colonies,
            # not to the queen DM history.
            if meta.get("colony_fork"):
                continue

            # Build a quick preview of the last human/assistant exchange.
            # We read all conversation parts, filter to client-facing messages,
            # and return the last assistant message content as a snippet.
            last_message: str | None = None
            message_count: int = 0
            # Last-activity timestamp — mtime of the latest client-facing message.
            # Falls back to session creation time for empty sessions. NOTE: the
            # session directory's own mtime is NOT reliable here — POSIX dir mtime
            # only updates when direct entries change, and conversation parts are
            # nested under conversations/parts/, so writing a new part does not
            # bubble up to the session dir.
            last_active_at: float = float(created_at) if isinstance(created_at, (int, float)) else 0.0
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
                    # Take the latest message's timestamp as the activity marker.
                    # _collect_parts sets created_at via setdefault to the part
                    # file's mtime, so this is always a valid float.
                    if client_msgs:
                        latest_ts = client_msgs[-1].get("created_at")
                        if isinstance(latest_ts, (int, float)) and latest_ts > last_active_at:
                            last_active_at = float(latest_ts)
                    # Last assistant message as preview snippet
                    for msg in reversed(client_msgs):
                        content = msg.get("content") or ""
                        if isinstance(content, list):
                            # Anthropic-style content blocks
                            content = " ".join(
                                b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                            )
                        if content and msg.get("role") == "assistant":
                            last_message = content[:120].strip()
                            break
                except OSError:
                    pass

            # Derive queen_id from directory structure: queens/{queen_id}/sessions/{session_id}
            queen_id = d.parent.parent.name if d.parent.name == "sessions" else None

            results.append(
                {
                    "session_id": d.name,
                    "cold": True,  # caller overrides for live sessions
                    "live": False,
                    "has_messages": convs_dir.exists() and message_count > 0,
                    "created_at": created_at,
                    "last_active_at": last_active_at,
                    "agent_name": agent_name,
                    "agent_path": agent_path,
                    "last_message": last_message,
                    "message_count": message_count,
                    "queen_id": queen_id,
                }
            )

        # Sort by last-activity timestamp, newest first. This is the order
        # callers (including /api/sessions/history and colony-chat cold resume)
        # rely on — don't use raw directory mtime, which doesn't update when
        # nested conversation parts are written.
        results.sort(key=lambda r: r.get("last_active_at") or 0.0, reverse=True)
        return results

    async def shutdown_all(self) -> None:
        """Gracefully stop all sessions. Called on server shutdown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.stop_session(sid)
        logger.info("All sessions stopped")
