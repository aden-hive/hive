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
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from framework.config import COLONIES_DIR, QUEENS_DIR
from framework.host.colony_binding import ColonyBinding
from framework.host.triggers import TriggerDefinition
from framework.utils.text import humanize_slug

logger = logging.getLogger(__name__)


def _generate_session_id() -> str:
    """Generate a unique session ID."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"session_{ts}_{uuid.uuid4().hex[:8]}"


def _queen_session_dir(
    session_id: str,
    queen_name: str = "default",
    colony_id: str | None = None,
) -> Path:
    """Return the on-disk directory for a queen session.

    Two homes depending on whether the queen is in a DM or running as
    a colony's overseer:

    - DM session   → ``queens/<queen>/sessions/<session_id>/``
    - Colony queen → ``colonies/<colony>/queens/<queen>/sessions/<session_id>/``

    The split lets ``rm -rf colonies/<c>/`` cleanly remove every overseer
    session tied to that colony, while leaving the queen's DM history alone.
    """
    from framework.config import colony_queen_session_dir, queen_session_dir

    if colony_id:
        return colony_queen_session_dir(colony_id, queen_name, session_id)
    return queen_session_dir(queen_name, session_id)


def _iter_queen_session_dirs(session_id: str) -> Iterator[Path]:
    """Yield every session dir matching ``session_id`` — across the queen DM
    tree and every colony's overseer sessions.

    The same ``session_id`` can appear under multiple colonies (a DM session
    forked into more than one colony keeps its id), so callers that need a
    *specific* one (e.g. the dir that actually holds a given attachment) must
    look at all candidates rather than the first match.
    """
    from framework.config import colony_queens_dir

    if QUEENS_DIR.exists():
        for queen_root in QUEENS_DIR.iterdir():
            if not queen_root.is_dir():
                continue
            candidate = queen_root / "sessions" / session_id
            if candidate.exists():
                yield candidate
    if COLONIES_DIR.exists():
        for colony_root in COLONIES_DIR.iterdir():
            if not colony_root.is_dir():
                continue
            queens_root = colony_queens_dir(colony_root.name)
            if not queens_root.exists():
                continue
            for queen_root in queens_root.iterdir():
                if not queen_root.is_dir():
                    continue
                candidate = queen_root / "sessions" / session_id
                if candidate.exists():
                    yield candidate


def _find_queen_session_dir(session_id: str) -> Path:
    """Search both queen DM sessions and every colony's overseer sessions
    for ``session_id``. Falls back to the default queen's sessions dir."""
    from framework.config import queen_session_dir

    for candidate in _iter_queen_session_dirs(session_id):
        return candidate
    return queen_session_dir("default", session_id)


def _colony_id_for_session_dir(session_dir: Path) -> str | None:
    """The colony slug owning ``session_dir``, or None for a queen DM session.

    The layout is ``colonies/<slug>/queens/<q>/sessions/<sid>``, so the slug is
    whichever path component sits directly under the ``colonies`` root.
    """
    for parent in session_dir.parents:
        if parent.parent is not None and parent.parent.name == "colonies":
            return parent.name
    return None


def _derive_resume_colony_id(session_id: str) -> str | None:
    """Return the colony slug whose tree holds ``session_id``, or None.

    Guards resumes that arrive without colony context (e.g. the desktop's
    session-gone auto-resume on the queen DM page): binding such a resume
    to no colony would make ``_start_queen`` materialize a duplicate empty
    session dir under the queen DM tree, which ``_find_queen_session_dir``
    then prefers over the real colony copy — the "blank history" bug.

    Reads through ``_iter_queen_session_dirs`` rather than walking the colony
    tree again. Two independent walks of the same layout is how the two halves
    of this bug drifted apart in the first place: that generator exists because
    a session id can match several dirs, which is the same fact this function
    depends on. Queen-DM candidates yield no colony and are skipped, so the
    first colony-owned match wins — the original behavior.
    """
    try:
        for candidate in _iter_queen_session_dirs(session_id):
            colony_id = _colony_id_for_session_dir(candidate)
            if colony_id is not None:
                return colony_id
    except OSError:
        return None
    return None


def _find_colony_queen_session_dir(
    colony_id: str,
    session_id: str,
    queen_name: str | None = None,
) -> Path | None:
    """Locate a colony queen-overseer session in the canonical colony tree.

    Walks ``colonies/<colony_id>/queens/<q>/sessions/<session_id>/``.
    Skips the queen DM tree entirely — callers with colony context should
    never accidentally resolve to a stale queen-tree fork snapshot. If
    ``queen_name`` is provided it's checked first; otherwise every queen
    under the colony is scanned.

    Returns ``None`` when no match exists. Callers handle absence
    explicitly rather than receiving a guessed default path.
    """
    from framework.config import colony_queens_dir

    root = colony_queens_dir(colony_id)
    if not root.exists():
        return None
    if queen_name:
        candidate = root / queen_name / "sessions" / session_id
        if candidate.exists():
            return candidate
    try:
        for queen_root in root.iterdir():
            if not queen_root.is_dir():
                continue
            candidate = queen_root / "sessions" / session_id
            if candidate.exists():
                return candidate
    except OSError:
        return None
    return None


def _latest_colony_queen_session_id(
    colony_id: str,
    queen_name: str | None = None,
) -> str | None:
    """Newest session id under a colony's own queen tree, or None.

    Repairs legacy colonies whose ``metadata.json`` predates the
    ``queen_session_id`` field: we adopt the colony's most-recently-active
    session *scoped to this colony* (so we never pick up a same-id session
    that belongs to a different colony) when no better hint is available.
    """
    from framework.config import colony_queens_dir

    root = colony_queens_dir(colony_id)
    if not root.exists():
        return None
    queen_roots = [root / queen_name] if queen_name else list(root.iterdir())
    newest: tuple[float, str] | None = None
    for queen_root in queen_roots:
        sessions_dir = queen_root / "sessions"
        if not sessions_dir.is_dir():
            continue
        try:
            for session_dir in sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue
                try:
                    mtime = session_dir.stat().st_mtime
                except OSError:
                    continue
                if newest is None or mtime > newest[0]:
                    newest = (mtime, session_dir.name)
        except OSError:
            continue
    return newest[1] if newest else None


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
    # Loaded colony (optional) — ``colony_id`` is the on-disk identity
    # (None for DM/queen-only sessions); ``binding`` is the materialized
    # :class:`ColonyBinding` (None until ``fork_session_into_colony`` or
    # the session-load path attaches one).
    binding: ColonyBinding | None = None
    worker_path: Path | None = None
    # Unified runtime: a real ColonyRuntime hosting the queen as overseer
    # and (in colony sessions) parallel workers spawned via
    # run_worker. Always set once _start_queen has run.
    colony: Any | None = None  # ColonyRuntime
    # Queen phase state (working/reviewing)
    phase_state: Any = None  # QueenPhaseState
    # Worker handoff subscription (colony-scoped escalation receiver)
    worker_handoff_sub: str | None = None
    # Pending worker escalations awaiting queen reply.
    # Keyed by request_id -> {worker_id, colony_id, reason, context, opened_at}.
    # Populated by queen_orchestrator._on_worker_escalation and drained by
    # the reply_to_worker tool.
    pending_escalations: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Live SSE client count — incremented/decremented by the events route as
    # browsers connect/disconnect. Sentinel reads this to tell whether a human
    # is watching (so it escalates to messaging only when nobody is attached).
    # A dedicated counter, NOT len(event_bus._subscriptions): that map also
    # holds webhook-trigger subscriptions, which are not UI clients.
    sse_client_count: int = 0
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
    pending_catch_up: list[str] = field(default_factory=list)
    # Session directory resumption:
    # When set, _start_queen writes queen conversations to this existing session's
    # directory instead of creating a new one.  This lets cold-restores accumulate
    # all messages in the original session folder so history is never fragmented.
    queen_resume_from: str | None = None
    # Queen session directory (set during _start_queen, used for shutdown reflection)
    queen_dir: Path | None = None
    # Multi-queen support: which queen profile this session uses
    queen_name: str = "default"
    # Opened through one of the desktop's CRM doors ("Set up my CRM" /
    # "Configure"). NOT derivable from ``queen_name``: the CRM's host queen
    # (``queen_growth``) is also the default queen and the auto-selection
    # fallback, so most growth-queen DMs have nothing to do with the CRM.
    # Setup-only behaviour (the reveal nudge) keys off this.
    crm_setup: bool = False
    # Colony name: set when a worker is loaded from a colony
    colony_id: str | None = None
    # Session mode discriminator. "dm" = queen DM session under
    # ~/.hive/agents/queens/{queen_id}/sessions/. "colony" = forked colony
    # session under ~/.hive/colonies/{colony_id}/sessions/, with the
    # queen running as the colony's overseer and the run_worker
    # tool unlocked. The mode is the canonical discriminator for storage
    # path, tool exposure, and SSE filtering — see the Phase 2 plan.
    mode: Literal["dm", "colony"] = "dm"
    # Set to True after the user clicks the COLONY_CREATED system message
    # in this DM. Locks the chat input — the user must compact+fork into a
    # fresh session before continuing the conversation. Persisted in
    # meta.json so the lock survives server restarts.
    colony_spawned: bool = False
    spawned_colony_id: str | None = None
    # Set when this session has been forked into a fresh one via
    # task_create(new_session=true). The session is retired: its queen
    # loop is stopped, the chat input is locked, and it is skipped when
    # auto-resolving which session to resume for the queen. Persisted in
    # meta.json so the retirement survives server restarts.
    superseded_by: str | None = None
    # True for a session freshly created BY a task_create(new_session=true)
    # fork, until it receives its first genuine user message. While set,
    # new_session is disarmed — the synthetic kickoff turn must not fork
    # again (that pivot was already consumed by the fork that made this
    # session). In-memory only: a cold-resumed session idles for /chat,
    # so the next message is genuine and the flag is moot after restart.
    fork_kickoff_pending: bool = False


def _deduplicate_colony_id(colony_id: str) -> str:
    """Return a colony_id that doesn't collide with an existing colony on disk.

    If ``colony_id`` is free, returns it unchanged.  Otherwise appends
    ``_2``, ``_3``, … until an unused slug is found.
    """
    if not (COLONIES_DIR / colony_id / "metadata.json").exists():
        return colony_id
    # Strip any existing numeric suffix so we count from the base name.
    import re

    m = re.match(r"^(.+?)_(\d+)$", colony_id)
    base = m.group(1) if m else colony_id
    n = 2
    while (COLONIES_DIR / f"{base}_{n}" / "metadata.json").exists():
        n += 1
    return f"{base}_{n}"


def _ensure_minimal_colony(colony_id: str, *, queen_name: str | None = None) -> Path:
    """Bootstrap a minimal colony directory at ``~/.hive/colonies/{colony_id}/``.

    Creates the directory, a ``metadata.json``, and a minimal ``worker.json``
    so the colony is discoverable by the agent discovery system and colony-chat
    can resolve it via ``agent_path``.  Returns the colony directory path.
    """
    from framework.config import COLONIES_DIR

    colony_dir = COLONIES_DIR / colony_id
    colony_dir.mkdir(parents=True, exist_ok=True)

    meta_path = colony_dir / "metadata.json"
    if not meta_path.exists():
        meta: dict = {
            "name": colony_id,
            "created_at": time.time(),
        }
        if queen_name:
            meta["queen_name"] = queen_name
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Minimal worker config so the colony dir is discoverable and
    # colony-chat can find the session via agent_path.
    worker_path = colony_dir / "worker.json"
    if not worker_path.exists():
        worker_config: dict = {
            "name": humanize_slug(colony_id),
            "description": f"Colony {colony_id}",
            "tools": [],
            "goal": {"description": f"Work on tasks for colony {colony_id}"},
        }
        if queen_name:
            worker_config["queen_name"] = queen_name
        worker_path.write_text(json.dumps(worker_config, indent=2), encoding="utf-8")

    return colony_dir


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
        from framework.storage.migrate_v2 import run_migration as run_v2

        try:
            run_v2()
        except Exception:
            logger.warning("v2 migration failed (non-fatal)", exc_info=True)

        # Run one-time v2 → v3 layout migration (queens/, colony self-containment,
        # tracker/ dir, memory flatten). Ordered after v2 so the v2 paths
        # the v3 migration reads are populated.
        from framework.storage.migrate_v3 import run_migration as run_v3

        try:
            run_v3()
        except Exception:
            logger.warning("v3 migration failed (non-fatal)", exc_info=True)

        # Consolidate any post-v3 colony_fork sessions that landed in the
        # queen tree instead of the canonical colony tree. Ordered after
        # v3 so the colony layout it relies on is already in place.
        from framework.storage.migrate_colony_sessions import (
            run_migration as run_colony_sessions,
        )

        try:
            run_colony_sessions()
        except Exception:
            logger.warning("colony_sessions migration failed (non-fatal)", exc_info=True)

        # Ensure every existing colony has tracker.db and patch worker
        # configs with the current ColonyBinding. Legacy ProgressDB /
        # loose tracker_db_path fields are stripped at the same time.
        from framework.host.tracker_db import ensure_all_colony_tracker_dbs

        try:
            ensured_tracker = ensure_all_colony_tracker_dbs()
            if ensured_tracker:
                logger.info(
                    "tracker_db: ensured %d colony tracker DB(s) at startup",
                    len(ensured_tracker),
                )
        except Exception:
            logger.warning("tracker_db: backfill at startup failed (non-fatal)", exc_info=True)

    def get_live_session(self, session_id: str) -> Session | None:
        """Return the in-memory session for ``session_id``, or None.

        Public accessor used by Sentinel to reach a parked queen for resume
        and to read ``sse_client_count``. Does not load from disk — a cold
        session must be restored via ``create_session(queen_resume_from=…)``.
        """
        return self._sessions.get(session_id)

    def build_llm(self, model: str | None = None):
        """Construct an LLM provider using the server's configured defaults."""
        from framework.config import RuntimeConfig, get_api_key, get_hive_config

        rc = RuntimeConfig(model=model or self._model or RuntimeConfig().model)
        llm_config = get_hive_config().get("llm", {})
        if llm_config.get("use_antigravity_subscription"):
            from framework.llm.antigravity import AntigravityProvider

            return AntigravityProvider(model=rc.model)

        from framework.llm.litellm import LiteLLMProvider

        # api_key_resolver lets desktop streamToken refreshes propagate to
        # this provider on every call — without requiring _hot_swap_sessions
        # to visit it. The snapshot in rc.api_key remains the default.
        return LiteLLMProvider(
            model=rc.model,
            api_key=rc.api_key,
            api_base=rc.api_base,
            api_key_resolver=get_api_key,
            **rc.extra_kwargs,
        )

    def build_worker_llm(self):
        """Construct a dedicated worker LLM when ``worker_llm`` is configured.

        Returns ``None`` when no ``worker_llm`` section is set in
        configuration.json — callers should fall back to ``session.llm``
        (i.e. workers continue to share the queen's LLM, legacy behavior).

        Uses the parallel ``get_worker_*`` accessors so api_key / api_base /
        extra_kwargs all come from the ``worker_llm`` config section, not
        the primary ``llm`` section.
        """
        from framework.config import (
            get_hive_config,
            get_preferred_worker_model,
            get_worker_api_base,
            get_worker_api_key,
            get_worker_llm_extra_kwargs,
        )

        model = get_preferred_worker_model()
        if not model:
            return None

        worker_cfg = get_hive_config().get("worker_llm", {})
        if worker_cfg.get("use_antigravity_subscription"):
            from framework.llm.antigravity import AntigravityProvider

            return AntigravityProvider(model=model)

        from framework.llm.litellm import LiteLLMProvider

        # Same resolver-based freshness as build_llm, scoped to worker_llm.
        return LiteLLMProvider(
            model=model,
            api_key=get_worker_api_key(),
            api_base=get_worker_api_base(),
            api_key_resolver=get_worker_api_key,
            **get_worker_llm_extra_kwargs(),
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

        Internal helper — use create_session().
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
        *,
        colony_id: str | None = None,
        session_id: str | None = None,
        model: str | None = None,
        initial_prompt: str | None = None,
        queen_resume_from: str | None = None,
        queen_name: str | None = None,
        initial_phase: str | None = None,
        crm_setup: bool = False,
    ) -> Session:
        """Create a new session with a queen, optionally bound to a colony.

        Colony resolution is by ``colony_id`` (the on-disk slug). The
        directory is always ``<COLONIES_DIR>/<colony_id>/``:

        - **Existing colony** (``metadata.json`` present): runs the full
          AgentLoader pipeline (MCP / skills / credentials), then starts
          the queen against it.
        - **Fresh colony** (no ``metadata.json``): bootstraps a minimal
          colony directory, then starts the queen in colony phase.
        - **No ``colony_id``**: queen-only DM session.

        When ``queen_resume_from`` is set the queen writes conversation
        messages to that existing session's directory instead of creating
        a new one — preserves full conversation history across restarts.

        When ``queen_name`` is set the session is pre-bound to that queen
        identity, skipping LLM auto-selection in the identity hook.
        """
        # A resume that arrives without colony context must not rebind the
        # session's storage: if the resumed session lives in a colony tree,
        # adopt that colony regardless of what the caller (didn't) pass.
        if queen_resume_from and not colony_id:
            derived = _derive_resume_colony_id(queen_resume_from)
            if derived:
                logger.info(
                    "Resume of '%s' arrived without colony context; derived colony_id='%s' from its on-disk location",
                    queen_resume_from,
                    derived,
                )
                colony_id = derived

        # A soft-deleted colony still has its metadata.json on disk, so without
        # this it would be treated as "existing" below and silently resurrected.
        # It's invisible and unrecoverable to the user, so a create_session
        # naming it can only mean "make a fresh colony here" — park the dead one
        # aside to free the name. No-op for a live colony (it opens as normal).
        if colony_id:
            from framework.host.colony_metadata import vacate_soft_deleted_colony

            vacate_soft_deleted_colony(colony_id)

        # -------- 1. Existing-colony branch (was create_session_with_worker_colony)
        if colony_id and (COLONIES_DIR / colony_id / "metadata.json").exists():
            # When initial_prompt is set the caller intends to *create* a new
            # colony (e.g. deploying a community prompt), not open the
            # existing one.  Deduplicate the slug so the user gets a fresh
            # colony instead of silently landing in the old one.
            #
            # Exception: a scaffold-only colony (metadata scaffolded=true —
            # the free-user flow's queen-less placeholder, see
            # handle_scaffold_colony). It has no history, and this create IS
            # its upgrade: reuse the dir instead of stranding it as an empty
            # husk next to a deduped "<name>_2". The flag is consumed inside
            # _create_session_for_existing_colony, so once a colony has run
            # it can never be mistaken for a scaffold again.
            if initial_prompt:
                from framework.host.colony_metadata import load_colony_metadata

                if load_colony_metadata(colony_id).get("scaffolded"):
                    return await self._create_session_for_existing_colony(
                        colony_id=colony_id,
                        session_id=session_id,
                        model=model,
                        initial_prompt=initial_prompt,
                        queen_resume_from=queen_resume_from,
                        queen_name=queen_name,
                        initial_phase=initial_phase,
                    )
                colony_id = _deduplicate_colony_id(colony_id)
                # After dedup the slug is free — fall through to the
                # fresh-colony-bootstrap branch below.
            else:
                return await self._create_session_for_existing_colony(
                    colony_id=colony_id,
                    session_id=session_id,
                    model=model,
                    initial_prompt=initial_prompt,
                    queen_resume_from=queen_resume_from,
                    queen_name=queen_name,
                    initial_phase=initial_phase,
                )

        # -------- 2. Queen-only or fresh-colony-bootstrap branch
        resolved_session_id = queen_resume_from or session_id
        session = await self._create_session_core(session_id=resolved_session_id, model=model)
        session.queen_resume_from = queen_resume_from
        if queen_name:
            session.queen_name = queen_name
        # Only ever set here — never cleared. A resume re-reads it from
        # meta.json (see prepare_queen_session), so the label survives the
        # restart a setup conversation is most likely to meet.
        if crm_setup:
            session.crm_setup = True

        if colony_id:
            # Fresh-colony bootstrap: minimal on-disk colony. Phase is
            # derived from these bindings inside create_queen — no
            # explicit phase override needed.
            colony_path = _ensure_minimal_colony(colony_id, queen_name=queen_name)
            session.colony_id = colony_id
            session.binding = ColonyBinding.for_name(colony_id)
            session.worker_path = colony_path
            session.mode = "colony"

        await self._start_queen(
            session,
            worker_identity=None,
            initial_prompt=initial_prompt,
            initial_phase=initial_phase,
        )

        logger.info(
            "Session '%s' created (queen-only, resume_from=%s, colony=%s)",
            session.id,
            queen_resume_from,
            colony_id,
        )
        return session

    async def _create_session_for_existing_colony(
        self,
        *,
        colony_id: str,
        session_id: str | None,
        model: str | None,
        initial_prompt: str | None,
        queen_resume_from: str | None,
        queen_name: str | None,
        initial_phase: str | None,
    ) -> Session:
        """Open an existing colony and start a queen against it.

        Internal helper for the colony-exists branch of ``create_session``.
        Runs the full AgentLoader pipeline via ``_load_worker_core``.
        """
        from framework.tools.queen_lifecycle_tools import normalize_legacy_phase

        agent_path = COLONIES_DIR / colony_id

        # Read colony metadata.json for queen provenance (queen_name,
        # queen_session_id) so we can restore the correct queen identity
        # and resume from the originating session when no explicit
        # queen_resume_from was provided.
        _colony_metadata: dict = {}
        _colony_metadata_path = agent_path / "metadata.json"
        try:
            _colony_metadata = json.loads(_colony_metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

        # Consume the scaffold marker (free-user placeholder, see
        # handle_scaffold_colony): the colony is getting a real session now,
        # so it must never again be treated as a reusable empty scaffold by
        # create_session's initial_prompt branch.
        if _colony_metadata.get("scaffolded"):
            try:
                from framework.host.colony_metadata import update_colony_metadata

                update_colony_metadata(colony_id, {"scaffolded": False})
            except OSError:
                logger.warning("Failed to clear scaffolded flag for colony '%s'", colony_id)

        if not queen_name:
            queen_name = _colony_metadata.get("queen_name") or None

        # Colony metadata's queen_session_id is the authoritative session
        # for this colony (the forked session). It takes priority over
        # whatever the frontend found via history scan.
        _colony_session_id = _colony_metadata.get("queen_session_id")
        if not _colony_session_id:
            # Legacy colony: metadata.json predates the queen_session_id
            # field, so we don't know which session is this colony's own.
            # Falling back to the frontend-supplied queen_resume_from and
            # resolving it *globally* is what lets two colonies that share a
            # session id (a DM session opened into more than one legacy
            # colony) cross-resolve into each other — the root of the
            # duplicate-id attachment 404s. Resolve it scoped to THIS colony
            # instead, then persist it so every later open is unambiguous.
            # Only repair when the frontend actually asked to resume a
            # session. If queen_resume_from is a session that lives under
            # THIS colony, honor it; if it points elsewhere (a stale or
            # cross-colony id), adopt this colony's own newest session
            # instead. When no resume was requested, leave the fresh-open
            # path untouched.
            _repaired: str | None = None
            if queen_resume_from:
                if _find_colony_queen_session_dir(colony_id, queen_resume_from, queen_name):
                    _repaired = queen_resume_from
                else:
                    _repaired = _latest_colony_queen_session_id(colony_id, queen_name)
            if _repaired:
                _colony_session_id = _repaired
                try:
                    from framework.host.colony_metadata import update_colony_metadata

                    update_colony_metadata(colony_id, {"queen_session_id": _repaired})
                    logger.info(
                        "Backfilled queen_session_id=%s for legacy colony '%s'",
                        _repaired,
                        colony_id,
                    )
                except (OSError, FileNotFoundError):
                    logger.warning(
                        "Could not backfill queen_session_id for colony '%s'",
                        colony_id,
                        exc_info=True,
                    )
        if _colony_session_id:
            queen_resume_from = _colony_session_id

        # When cold-restoring, check meta.json for the phase — if the
        # agent was still being built we must NOT try to load the worker
        # (the code is incomplete and will fail to import).
        _resume_queen_id: str | None = None
        if queen_resume_from:
            _resume_phase = None
            _meta_path = _find_queen_session_dir(queen_resume_from) / "meta.json"
            if _meta_path.exists():
                try:
                    _meta = json.loads(_meta_path.read_text(encoding="utf-8"))
                    _resume_phase = normalize_legacy_phase(_meta.get("phase"))
                    _resume_queen_id = _meta.get("queen_id")
                except (json.JSONDecodeError, OSError):
                    pass
            if _resume_phase in ("building", "planning"):
                # Fall back to queen-only session — the colony code is
                # incomplete; opening it would crash. Phase resolves to
                # whatever meta.json says inside create_queen.
                return await self.create_session(
                    session_id=session_id,
                    model=model,
                    initial_prompt=initial_prompt,
                    queen_resume_from=queen_resume_from,
                    queen_name=queen_name or _resume_queen_id,
                )

        # If this colony's live session already exists (user navigated
        # back), return it directly — but only if it points at the same
        # colony directory.
        if queen_resume_from and queen_resume_from in self._sessions:
            existing = self._sessions[queen_resume_from]
            if existing.worker_path and str(existing.worker_path) == str(agent_path):
                return existing

        # When the queen forked this colony, the inherited DM transcript
        # is compacted in the background. Block until it finishes so
        # _load_worker_core reads the compacted summary, not the raw
        # transcript. Bounded wait so a stuck compactor can't brick the
        # colony.
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
            await self._load_worker_core(session, colony_id=colony_id, model=model)

            await self._start_queen(
                session,
                worker_identity=None,
                initial_prompt=initial_prompt,
                initial_phase=initial_phase,
            )
        except Exception:
            if queen_resume_from:
                # Cold restore: worker load failed (e.g. incomplete code
                # or deleted colony dir). Fall back to queen-only so the
                # user can continue the conversation. Forward queen_name
                # so the recovered session is stored under the correct
                # queen identity.
                logger.warning(
                    "Cold restore: worker load failed for colony '%s', falling back to queen-only",
                    colony_id,
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
            # Non-cold-restore failure: tear down and propagate.
            await self.stop_session(session.id)
            raise
        return session

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------

    async def _load_worker_core(
        self,
        session: Session,
        colony_id: str,
        model: str | None = None,
    ) -> None:
        """Bind a colony to a session and load its triggers.

        Resolves the colony directory from ``colony_id`` (always
        ``<COLONIES_DIR>/<colony_id>/``), sets the session's colony
        identity (``colony_id``, ``binding``, ``worker_path``), and
        auto-starts any triggers flagged active in ``triggers.json``.
        Does NOT notify the queen — callers handle that step. ``model``
        is accepted for caller compatibility but is unused now that
        workers no longer load a graph runtime.
        """
        agent_path = COLONIES_DIR / colony_id

        if session.colony_id is not None:
            raise ValueError(f"Session '{session.id}' already has colony '{session.colony_id}'")

        async with self._lock:
            if session.id in self._loading:
                raise ValueError(f"Session '{session.id}' is currently loading a colony")
            self._loading.add(session.id)

        try:
            # Triggers live in the colony's triggers.json — one file holding
            # each trigger's definition plus an ``active`` flag. Load every
            # definition; auto-start the ones flagged active so they survive
            # a server restart without the user re-activating them.
            from framework.tools.queen_lifecycle_tools import (
                _persist_active_triggers,
                _read_agent_triggers_json,
                _save_trigger_to_agent,
                _start_trigger_timer,
                _start_trigger_webhook,
            )

            triggers_to_autostart: list[str] = []
            for tdata in _read_agent_triggers_json(agent_path):
                tid = tdata.get("id", "")
                ttype = tdata.get("trigger_type", "")
                if tid and ttype in ("timer", "webhook"):
                    # A missing ``enabled`` key means the trigger was
                    # registered without an explicit choice; default
                    # to True — every persisted trigger is enabled
                    # unless someone has flipped the advanced toggle.
                    enabled_flag = bool(tdata.get("enabled", True))
                    session.available_triggers[tid] = TriggerDefinition(
                        id=tid,
                        trigger_type=ttype,
                        trigger_config=tdata.get("trigger_config", {}),
                        description=tdata.get("name", tid),
                        task=tdata.get("task", ""),
                        enabled=enabled_flag,
                        last_fired_at=tdata.get("last_fired_at"),
                        next_due_at=tdata.get("next_due_at"),
                    )
                    if enabled_flag:
                        triggers_to_autostart.append(tid)
                    logger.info("Loaded trigger '%s' (%s) from triggers.json", tid, ttype)

            # Bind the colony identity before starting triggers — the trigger
            # fire path gates on ``session.colony_id``.
            session.colony_id = colony_id
            session.binding = ColonyBinding.for_name(colony_id)
            session.worker_path = agent_path

            # Silently skip missed triggers: stamp last_fired_at = now so
            # the gap doesn't resurface on the next reopen. Colonies should
            # not auto-start work on open — only explicit user messages and
            # scheduled trigger fires activate them.
            from datetime import datetime

            from framework.host.triggers import compute_missed

            persisted_triggers = _read_agent_triggers_json(agent_path)
            missed = compute_missed(persisted_triggers)
            if missed:
                now_iso = datetime.now(tz=UTC).isoformat()
                for m in missed:
                    tid = m.trigger_id
                    tdef = session.available_triggers.get(tid)
                    if tdef is not None:
                        tdef.last_fired_at = now_iso
                        _save_trigger_to_agent(session, tid, tdef)
                logger.info(
                    "Silently skipped %d missed trigger(s) on colony load: %s",
                    len(missed),
                    [m.trigger_id for m in missed],
                )

            for tid in triggers_to_autostart:
                tdef = session.available_triggers[tid]
                try:
                    if tdef.trigger_type == "timer":
                        await _start_trigger_timer(session, tid, tdef)
                    elif tdef.trigger_type == "webhook":
                        await _start_trigger_webhook(session, tid, tdef)
                    session.active_trigger_ids.add(tid)
                    logger.info("Auto-started trigger '%s' on colony load", tid)
                except Exception:
                    logger.warning(
                        "Failed to auto-start trigger '%s' on colony load",
                        tid,
                        exc_info=True,
                    )

            if session.available_triggers:
                # Sync triggers.json ``active`` flags with what is running,
                # then tell the UI which triggers exist and which are active.
                await _persist_active_triggers(session, session.id)
                await self._emit_trigger_events(session, "available", session.available_triggers)
                if session.active_trigger_ids:
                    activated = {tid: session.available_triggers[tid] for tid in session.active_trigger_ids if tid in session.available_triggers}
                    if activated:
                        await self._emit_trigger_events(session, "activated", activated)

            # Clean up stale "active" sessions from previous (dead) processes
            self._cleanup_stale_active_sessions(agent_path)

            async with self._lock:
                self._loading.discard(session.id)

            logger.info(
                "Colony '%s' bound to session '%s'",
                colony_id,
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
        from framework.config import HIVE_HOME

        sessions_path = HIVE_HOME / "agents" / agent_path.name / "sessions"
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

    async def load_colony(
        self,
        session_id: str,
        colony_id: str,
        model: str | None = None,
    ) -> Session:
        """Load a colony into an existing session (with running queen).

        Resolves the colony directory from ``colony_id`` (always
        ``<COLONIES_DIR>/<colony_id>/``), starts the colony runtime, and
        notifies the queen.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError(f"Session '{session_id}' not found")

        await self._load_worker_core(session, colony_id=colony_id, model=model)

        agent_path = COLONIES_DIR / colony_id

        # Notify queen about the loaded worker (skip for queen itself).
        if colony_id != "queen" and session.colony_id:
            await self._notify_queen_colony_loaded(session)

        # Update meta.json so cold-restore can discover this session
        storage_session_id = session.queen_resume_from or session.id
        meta_path = _queen_session_dir(storage_session_id, session.queen_name) / "meta.json"
        try:
            _agent_name = humanize_slug(colony_id)
            existing_meta = {}
            if meta_path.exists():
                existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_meta["agent_name"] = _agent_name
            existing_meta["agent_path"] = str(session.worker_path) if session.worker_path else str(agent_path)
            meta_path.write_text(json.dumps(existing_meta), encoding="utf-8")
        except OSError:
            pass

        # Emit SSE event so the frontend can update UI
        await self._emit_colony_loaded(session)

        return session

    async def unload_colony(self, session_id: str) -> bool:
        """Unload the worker colony from a session. Queen stays alive."""
        session = self._sessions.get(session_id)
        if session is None:
            return False
        if session.colony_id is None:
            return False

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
        session.binding = None
        session.worker_path = None

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

                # asyncio.create_task() requires a coroutine — wrapping in
                # asyncio.shield() (which returns a Future) raised
                # TypeError on every stop. The task is tracked in
                # _background_tasks and never cancelled by us, so it
                # already runs to completion without shielding.
                task = asyncio.create_task(
                    run_shutdown_reflection(
                        session.queen_dir,
                        session.llm,
                        global_memory_dir_override=global_mem_dir,
                        queen_memory_dir=queen_mem_dir,
                        queen_id=session.queen_name,
                    ),
                    name=f"shutdown-reflect-{session_id}",
                )
                logger.info("Session '%s': shutdown reflection spawned", session_id)
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError as exc:
                # Most common when a session is stopped after the event loop
                # has closed (e.g. during server shutdown or from an atexit
                # handler). The reflection would have had nothing to write
                # anyway — no new turns since the last periodic reflection.
                logger.warning(
                    "Session '%s': shutdown reflection skipped — event loop unavailable (%s). "
                    "Normal during server shutdown; anything worth persisting was saved by the "
                    "periodic reflection after the last turn.",
                    session_id,
                    exc,
                )
            except Exception as exc:
                logger.warning(
                    "Session '%s': failed to spawn shutdown reflection: %s: %s. "
                    "Check that queen_dir exists and session.llm is configured; full traceback follows.",
                    session_id,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

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
        # directory so that all messages accumulate in one place. A
        # colony-attached session writes under
        # ``colonies/<c>/queens/<q>/sessions/...``; a pure DM session
        # writes under ``queens/<q>/sessions/...``.
        storage_session_id = session.queen_resume_from or session.id
        queen_dir = _queen_session_dir(storage_session_id, session.queen_name, colony_id=session.colony_id)
        queen_dir.mkdir(parents=True, exist_ok=True)
        session.queen_dir = queen_dir

        # Always write/update session metadata so history sidebar has correct
        # agent name, path, and last-active timestamp (important so the original
        # session directory sorts as "most recent" after a cold-restore resume).
        _meta_path = queen_dir / "meta.json"
        try:
            _agent_name = str(session.worker_path.name).replace("_", " ").title() if session.worker_path else None
            # Merge into existing meta.json to preserve fields written by
            # _update_meta_json (e.g. phase, agent_path set during building).
            _existing_meta: dict = {}
            if _meta_path.exists():
                try:
                    _existing_meta = json.loads(_meta_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            _new_meta: dict = {
                "queen_id": session.queen_name,
            }
            # Preserve created_at on cold-resume. This used to be
            # `time.time()` unconditionally — which bumped a session's
            # creation date to "now" every time it reactivated, so a
            # session originally created weeks ago would suddenly show
            # up in the dropdown's "today's sessions" filter after the
            # user opened the queen DM and triggered an auto-resume.
            # Only stamp a fresh value when the session is genuinely
            # new (no prior created_at on disk).
            if not _existing_meta.get("created_at"):
                _new_meta["created_at"] = time.time()
            if _agent_name is not None:
                _new_meta["agent_name"] = _agent_name
            if session.worker_path is not None:
                _new_meta["agent_path"] = str(session.worker_path)
            # Explicit colony binding, so colony membership can be read from
            # meta.json without falling back to the agent_path basename.
            if session.colony_id:
                _new_meta["colony_id"] = session.colony_id
            _existing_meta.update(_new_meta)
            _meta_path.write_text(json.dumps(_existing_meta), encoding="utf-8")
            # Hydrate colony-spawned lock state from meta.json so the lock
            # survives server restart / cold-resume into a live session.
            if _existing_meta.get("colony_spawned") is True:
                session.colony_spawned = True
                _spawned_name = _existing_meta.get("spawned_colony_id")
                if isinstance(_spawned_name, str):
                    session.spawned_colony_id = _spawned_name
        except OSError:
            pass

        # Enable per-session event persistence so that all eventbus events
        # survive server restarts and can be replayed on cold-session resume.
        # Scan the existing event log to find the max iteration ever written,
        # then use max+1 as offset so resumed sessions produce monotonically
        # increasing iteration values — preventing frontend message ID collisions.
        # Phase is resolved separately inside create_queen from meta.json["phase"].
        # If the retention janitor is mid-rewrite of this session's
        # events.jsonl (cold-session hygiene), wait for it to release the
        # session lock before scanning/opening the file — racing the
        # tmp+rename would leave our append fd on the orphaned old inode.
        # The lock only wraps the rewrite itself (seconds even for a
        # multi-hundred-MB file); 240 polls = 120s upper bound before we
        # log and proceed rather than wedging session start forever.
        _janitor_lock = queen_dir / ".janitor.lock"
        for _i in range(240):
            try:
                if time.time() - _janitor_lock.stat().st_mtime > 3600:
                    break  # stale lock from a crashed janitor — ignore
            except OSError:
                break  # no lock
            if _i == 239:
                logger.warning(
                    "Session '%s': janitor lock still fresh after 120s; proceeding",
                    session.id,
                )
            await asyncio.sleep(0.5)

        events_path = queen_dir / "events.jsonl"

        def _scan_iteration_offset() -> int:
            """Full-file scan for max(iteration). Runs in a worker thread:
            imported/long-lived sessions carry events.jsonl files of tens
            of MB, and parsing them on the event loop froze the whole
            server (every SSE stream and request) for each session open."""
            offset = 0
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
                                it = evt.get("data", {}).get("iteration")
                                if isinstance(it, int) and it > max_iter:
                                    max_iter = it
                            except (json.JSONDecodeError, TypeError):
                                continue
                    if max_iter >= 0:
                        offset = max_iter + 1
            except OSError:
                pass
            return offset

        iteration_offset = await asyncio.to_thread(_scan_iteration_offset)
        if iteration_offset > 0:
            logger.info(
                "Session '%s' resuming with iteration_offset=%d (from events.jsonl max)",
                session.id,
                iteration_offset,
            )
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
        # the run_worker tool (Phase 4) will use this runtime
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
        is dormant fan-out infrastructure: ``run_worker``
        (Phase 4) is what activates it.
        """
        from framework.agent_loop.types import AgentSpec
        from framework.host.colony_runtime import ColonyConfig, ColonyRuntime
        from framework.schemas.goal import Goal

        queen_tools = getattr(session, "_queen_tools", None) or []
        queen_tool_executor = getattr(session, "_queen_tool_executor", None)

        # Resolve the colony runtime config. Precedence per knob:
        # per-colony metadata.json (set at create_colony time / colony
        # settings) > global configuration.json (desktop Developer
        # toggle, via get_adaptive_tool_budget_enabled) > framework
        # default in ColonyConfig() (env-seeded). Resolved here — per
        # session start, not import time — so toggling the global flag
        # applies to new sessions without a runtime restart.
        _colony_config: ColonyConfig | None = None
        try:
            _cfg_kwargs: dict[str, Any] = {}
            from framework.config import get_adaptive_tool_budget_enabled

            _cfg_kwargs["adaptive_tool_budget"] = get_adaptive_tool_budget_enabled()
            colony_id = getattr(session, "colony_id", None)
            if colony_id:
                from framework.config import COLONIES_DIR

                _meta_path = COLONIES_DIR / colony_id / "metadata.json"
                if _meta_path.exists():
                    import json as _json

                    _meta = _json.loads(_meta_path.read_text(encoding="utf-8"))
                    _meta_overrides: dict[str, Any] = {}
                    _max_conc = _meta.get("max_concurrent_workers")
                    if isinstance(_max_conc, int) and _max_conc > 0:
                        _meta_overrides["max_concurrent_workers"] = _max_conc
                    # Per-colony pin of adaptive worker budgets beats the
                    # global Developer toggle. Same resolution point as
                    # the concurrency cap so the knobs behave identically.
                    _adaptive = _meta.get("adaptive_tool_budget")
                    if isinstance(_adaptive, bool):
                        _meta_overrides["adaptive_tool_budget"] = _adaptive
                    if _meta_overrides:
                        _cfg_kwargs.update(_meta_overrides)
                        logger.info(
                            "_start_queen: applying colony config overrides %s for '%s'",
                            _meta_overrides,
                            colony_id,
                        )
            _colony_config = ColonyConfig(**_cfg_kwargs)
        except Exception:
            logger.debug(
                "_start_queen: failed to resolve colony config overrides (using defaults)",
                exc_info=True,
            )

        colony_spec = AgentSpec(
            id="queen_colony",
            name="Queen Colony",
            description=("Unified colony runtime hosting the queen overseer and any parallel workers spawned via run_worker."),
            system_prompt="",
            tools=[t.name for t in queen_tools],
            tool_access_policy="all",
        )

        colony_goal = Goal(
            id=f"colony_goal_{session.id}",
            name=f"Session {session.id}",
            description="Default goal for the session-level ColonyRuntime.",
        )

        # Parallel workers spawned via run_worker run inside this
        # ColonyRuntime and inherit its ``_llm``. If the user has configured
        # a dedicated worker_llm (e.g. desktop ships hive-2.1 for the queen
        # + hive-swarm for workers), use it here — otherwise fall back to
        # session.llm so workers share the queen's LLM (legacy behavior).
        # The queen itself runs in queen_orchestrator with session.llm and
        # is unaffected by this swap.
        worker_llm = self.build_worker_llm() or session.llm
        # Resolve the on-disk binding (when this session is attached to a
        # forked colony). DM sessions construct the runtime with
        # ``binding=None``; ``fork_session_into_colony`` installs the
        # real binding once the queen names her colony.
        _colony_id = getattr(session, "colony_id", None)
        _binding: ColonyBinding | None = getattr(session, "binding", None)
        if _binding is None and _colony_id:
            _binding = ColonyBinding.for_name(_colony_id)
            session.binding = _binding
        _colony_runtime_kwargs: dict[str, Any] = {
            "agent_spec": colony_spec,
            "goal": colony_goal,
            "storage_path": queen_dir,
            "llm": worker_llm,
            "tools": queen_tools,
            "tool_executor": queen_tool_executor,
            "event_bus": session.event_bus,
            "stream_id": session.id,
            "binding": _binding,
            "queen_id": getattr(session, "queen_name", None) or None,
            "pipeline_stages": [],  # queen pipeline runs in queen_orchestrator, not here
        }
        if _colony_config is not None:
            _colony_runtime_kwargs["config"] = _colony_config
        colony = ColonyRuntime(**_colony_runtime_kwargs)

        # Per-colony tool allowlist, loaded from the colony's metadata.json
        # when this session is attached to a real forked colony. For pure
        # queen DM sessions (session.colony_id is None) we only capture
        # the MCP-origin set — the allowlist stays ``None`` so every MCP
        # tool passes through by default.
        try:
            mcp_tool_names_all: set[str] = set()
            mgr_catalog = getattr(self, "_mcp_tool_catalog", None)
            if isinstance(mgr_catalog, dict):
                for entries in mgr_catalog.values():
                    for entry in entries:
                        name = entry.get("name") if isinstance(entry, dict) else None
                        if name:
                            mcp_tool_names_all.add(name)
            enabled_mcp_tools: list[str] | None = None
            colony_id = getattr(session, "colony_id", None)
            if colony_id:
                # Colony tool allowlist lives in a dedicated tools.json
                # sidecar next to metadata.json. The helper migrates any
                # legacy field out of metadata.json on first read.
                from framework.host.colony_tools_config import load_colony_tools_config

                enabled_mcp_tools = load_colony_tools_config(colony_id)
            colony.set_tool_allowlist(enabled_mcp_tools, mcp_tool_names_all)
        except Exception:
            logger.debug(
                "Colony allowlist bootstrap failed for session %s",
                session.id,
                exc_info=True,
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
        executor = session.queen_executor
        if executor is None:
            return
        node = executor.node_registry.get("queen")
        if node is None or not hasattr(node, "inject_event"):
            return

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

        await node.inject_event(f"[SYSTEM] Colony loaded.{trigger_lines}")

    async def _emit_colony_loaded(self, session: Session) -> None:
        """Publish a WORKER_COLONY_LOADED event so the frontend can update."""
        from framework.host.event_bus import AgentEvent, EventType

        await session.event_bus.publish(
            AgentEvent(
                type=EventType.WORKER_COLONY_LOADED,
                stream_id="queen",
                data={
                    "colony_id": session.colony_id,
                    "agent_path": str(session.worker_path) if session.worker_path else "",
                    "goal": "",
                    "node_count": 0,
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
                    },
                )
            )

    async def revive_queen(self, session: Session) -> None:
        """Revive a dead queen executor on an existing session.

        Restarts the queen with the same session context (tools, etc.).
        """
        logger.debug(
            "[revive_queen] Starting revival for session '%s', current queen_executor=%s",
            session.id,
            session.queen_executor,
        )

        # Workers no longer carry a graph-based profile.
        worker_identity = None

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

    def is_loading(self, session_id: str) -> bool:
        return session_id in self._loading

    def list_sessions(self) -> list[Session]:
        return list(self._sessions.values())

    # ------------------------------------------------------------------
    # Skill override helpers — used by routes_skills to find every live
    # SkillsManager affected by a queen- or colony-scope mutation so a
    # single HTTP call can reload them all.
    # ------------------------------------------------------------------

    def iter_queen_sessions(self, queen_id: str):
        """Yield live sessions whose queen matches ``queen_id``."""
        for s in self._sessions.values():
            if getattr(s, "queen_name", None) == queen_id:
                yield s

    def iter_colony_runtimes(
        self,
        *,
        queen_id: str | None = None,
        colony_id: str | None = None,
    ):
        """Yield live ``ColonyRuntime`` instances matching the filters.

        ``queen_id`` alone → every runtime whose ``queen_id`` matches
        (useful when the user toggles a queen-scope skill — all her
        colonies must reload).  ``colony_id`` alone → the single
        runtime pinned to that colony.  Both → intersection. No filters
        → every live runtime (used by global ``/api/skills`` reload).
        """
        for s in self._sessions.values():
            colony = getattr(s, "colony", None)
            if colony is None:
                continue
            if queen_id is not None and getattr(colony, "queen_id", None) != queen_id:
                continue
            if colony_id is not None and getattr(colony, "colony_id", None) != colony_id:
                continue
            yield colony

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
        spawned_colony_id: str | None = None
        meta_path = queen_dir / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agent_name = meta.get("agent_name")
                agent_path = meta.get("agent_path")
                created_at = meta.get("created_at") or created_at
                colony_spawned = bool(meta.get("colony_spawned"))
                _spawned = meta.get("spawned_colony_id")
                if isinstance(_spawned, str):
                    spawned_colony_id = _spawned
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
            "spawned_colony_id": spawned_colony_id,
        }

    @staticmethod
    def _summarize_session_dir(
        d: Path,
        *,
        skip_colony_fork: bool,
    ) -> dict | None:
        """Build the public session summary dict for one session directory.

        Shared between ``list_cold_sessions`` (queen DM history) and
        ``list_colony_sessions`` (per-colony overseer history). Returns
        ``None`` when the dir should be omitted from the listing.

        ``skip_colony_fork`` keeps the legacy filter on the queen-tree
        listing so any pre-migration ``colony_fork`` snapshots stay
        hidden from queen DM history. The colony listing passes False
        because those sessions ARE the colony's own chats.
        """
        if not d.is_dir():
            return None
        try:
            created_at = d.stat().st_ctime
        except OSError:
            created_at = 0.0

        agent_name: str | None = None
        agent_path: str | None = None
        meta: dict = {}
        meta_path = d / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agent_name = meta.get("agent_name")
                agent_path = meta.get("agent_path")
                created_at = meta.get("created_at") or created_at
            except (json.JSONDecodeError, OSError):
                pass

        if skip_colony_fork and meta.get("colony_fork"):
            return None

        # Preview of the last client-facing exchange. Cached in
        # ``summary.json`` next to ``meta.json`` so the sidebar doesn't
        # have to rescan every part on each list call. The cache is
        # written incrementally by FileConversationStore.write_part; if
        # missing or stale (parts dir mtime newer than the summary file)
        # we do a one-time full rebuild and write a fresh summary.
        #
        # NOTE on activity timestamps: the session directory's own mtime
        # is NOT reliable as a "last activity" marker — POSIX dir mtime
        # only updates when direct entries change, and conversation
        # parts live under conversations/parts/, so writing a new part
        # does not bubble up to the session dir.
        from framework.storage import session_summary

        last_message: str | None = None
        message_count: int = 0
        last_active_at: float = float(created_at) if isinstance(created_at, (int, float)) else 0.0
        convs_dir = d / "conversations"

        summary: dict | None = None
        if convs_dir.exists():
            if session_summary.is_stale(d):
                summary = session_summary.rebuild_summary(d)
            else:
                summary = session_summary.read_summary(d)

        if summary is not None:
            message_count = int(summary.get("message_count") or 0)
            last_message = summary.get("last_message")
            cached_active = summary.get("last_active_at")
            if isinstance(cached_active, (int, float)) and cached_active > last_active_at:
                last_active_at = float(cached_active)

        # Derive queen_id from directory structure. Works for both layouts:
        #   queens/<q>/sessions/<sid>                          -> parent.parent = <q>
        #   colonies/<c>/queens/<q>/sessions/<sid>             -> parent.parent = <q>
        queen_id = d.parent.parent.name if d.parent.name == "sessions" else None

        return {
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

    @staticmethod
    def list_cold_sessions() -> list[dict]:
        """Return metadata for every queen DM session directory on disk, newest first.

        Skips entries marked ``colony_fork: true`` — those belong to a
        colony's overseer history (``list_colony_sessions``), not the
        queen's DM history.
        """
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
            entry = SessionManager._summarize_session_dir(d, skip_colony_fork=True)
            if entry is not None:
                results.append(entry)

        # Strict newest-*created* first. ``session_id`` is the directory name
        # ``session_YYYYMMDD_HHMMSS_<hash>``, so a descending string sort is a
        # creation-time sort — total and deterministic (the hash uniquely
        # breaks same-second ties). Callers (/api/sessions/history,
        # colony-chat cold resume) rely on a stable "latest first" order;
        # ``last_active_at`` had no tiebreak, so equal values fell back to
        # undefined ``iterdir()`` filesystem order.
        results.sort(key=lambda r: r.get("session_id") or "", reverse=True)
        return results

    @staticmethod
    def list_colony_sessions(colony_id: str) -> list[dict]:
        """Return per-colony overseer session metadata, newest first.

        Walks ``colonies/<colony_id>/queens/<q>/sessions/<sid>/`` —
        the canonical home for colony queen-overseer sessions. The
        legacy ``colony_fork`` filter is intentionally NOT applied here
        because these are the colony's own chats. Returns an empty list
        for unknown colonies (don't 404 from callers — empty is the
        natural "no prior chat" state).
        """
        from framework.config import colony_queens_dir

        queens_root = colony_queens_dir(colony_id)
        if not queens_root.exists():
            return []

        all_session_dirs: list[Path] = []
        try:
            for queen_root in queens_root.iterdir():
                if not queen_root.is_dir():
                    continue
                sessions_dir = queen_root / "sessions"
                if not sessions_dir.exists():
                    continue
                for d in sessions_dir.iterdir():
                    if d.is_dir():
                        all_session_dirs.append(d)
        except OSError:
            return []

        results: list[dict] = []
        for d in all_session_dirs:
            entry = SessionManager._summarize_session_dir(d, skip_colony_fork=False)
            if entry is not None:
                results.append(entry)

        # Strict newest-created first by ``session_id`` (the dir name encodes
        # the creation timestamp) — total and deterministic, see the note in
        # ``list_cold_sessions``.
        results.sort(key=lambda r: r.get("session_id") or "", reverse=True)
        return results

    @staticmethod
    def get_colony_active_session(colony_id: str) -> dict | None:
        """Return the most-recently-active overseer session for the
        colony, or None when no session has produced messages yet.

        "Active" is implicit (newest ``last_active_at``); we don't
        persist an explicit pointer. Sessions with no messages are
        skipped so a freshly-clicked-but-never-typed colony doesn't
        accidentally claim the slot from a real prior chat.
        """
        for entry in SessionManager.list_colony_sessions(colony_id):
            if entry.get("has_messages"):
                return entry
        return None

    async def shutdown_all(self) -> None:
        """Gracefully stop all sessions. Called on server shutdown."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.stop_session(sid)
        logger.info("All sessions stopped")
