"""Framework-level reminder injection.

A *reminder* is advisory context the agent loop injects at well-known
points — distinct from config-driven hooks (``run_hooks``) and from
reactive error corrections. Reminders are framework-defined: a
:class:`ReminderSource` registers with the :class:`ReminderHub` and is
consulted at the :class:`ReminderPoint`\\ (s) it declares.

Points come in two flavours:

*Lifecycle points* — fired synchronously by the loop when it reaches a
known code location::

    SESSION_START      — once, at session bringup
    USER_PROMPT_SUBMIT — each time a user / external message arrives
    POST_TOOL_USE      — after a tool batch executes (rides the result tail)
    PRE_COMPACT        — before context compaction
    POST_COMPACT       — after context compaction (re-announce into the fresh
                         post-summary context; for surfaces invisible to the
                         model unless announced — deferred tools, skills)
    STOP               — when the agent yields after a text-only turn

*Temporal points* — fired by a hub-owned background ticker on a clock,
so a source can intervene even while the loop is parked::

    IDLE_TICK          — periodic; sources see a :class:`LoopSignals`
                         snapshot and decide whether to nudge

For lifecycle points the loop calls :meth:`ReminderHub.fire` and places
the wrapped ``<system-reminder>`` block itself. For temporal points the
hub's ticker calls :meth:`ReminderHub.collect`, parks whatever the
sources produce, and the loop drains it via :meth:`take_pending` at its
next iteration boundary — so conversation writes never race the loop.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class ReminderPoint(StrEnum):
    """Points at which the loop / ticker consults reminder sources."""

    # Lifecycle points — fired inline by the loop.
    SESSION_START = "session_start"
    USER_PROMPT_SUBMIT = "user_prompt_submit"
    POST_TOOL_USE = "post_tool_use"
    # Fired when the per-turn tool-call budget crosses a new soft multiple
    # (rides the current turn's tool_result tail) and again when the hard
    # limit is hit (merged into the deferred-advisory posted for next turn).
    # Sources fire at both sites — the loop owns timing.
    TOOL_BUDGET_CHECKPOINT = "tool_budget_checkpoint"
    PRE_COMPACT = "pre_compact"
    # Fired by the loop right AFTER compaction finishes, so a source can
    # re-announce context that the summary dropped and that the model cannot
    # otherwise see (deferred-tool manifest, skills catalog). Placed into the
    # fresh post-compact conversation, not summarized.
    POST_COMPACT = "post_compact"
    STOP = "stop"
    # Temporal point — fired by the hub-owned ticker on a clock.
    IDLE_TICK = "idle_tick"
    # Reactive point — consulted synchronously the moment a stream stalls.
    STREAM_STALLED = "stream_stalled"


class Placement(StrEnum):
    """Where a rendered reminder should land in the conversation."""

    USER_MESSAGE = "user_message"
    TOOL_RESULT_TAIL = "tool_result_tail"


class LoopActivity(StrEnum):
    """The agent loop's authoritative top-level state.

    Three mutually-exclusive values — at any instant the loop is in exactly
    one. The loop itself owns and announces this (see ``AgentLoop._activity``
    / ``LOOP_STATE_CHANGED``); it is *not* re-derived from scattered events.

      * ``EXECUTING`` — making progress: streaming an LLM call, running
        tools, between-turn / judge work, or compacting context.
      * ``AWAITING_USER`` — the agent *itself* deliberately ended its turn
        and parked (see :attr:`ParkReason.activity`).
      * ``INTERRUPTED`` — not moving and *not* a deliberate end-of-turn: an
        abnormal park, a stream stall, or a crashed / stale loop.
    """

    EXECUTING = "executing"
    AWAITING_USER = "awaiting_user"
    INTERRUPTED = "interrupted"


class InterruptCause(StrEnum):
    """Why a loop is :attr:`LoopActivity.INTERRUPTED` for a reason that is
    *not* a park — these have no :class:`ParkReason`.

    An interrupted park instead carries its ``ParkReason`` (``LLM_ERROR``,
    ``USER_STOPPED``, …); these cover the non-park cases.
    """

    STREAM_STALL = "stream_stall"  # the TTFT / inter-event watchdog tripped
    CRASHED = "crashed"  # execute() exited abnormally
    STALE = "stale"  # no events past the staleness window (snapshot-assigned)


class ParkReason(StrEnum):
    """Why the agent loop is parked at ``_await_user_input``.

    The single ``awaiting_input`` boolean has a blind spot: it cannot tell
    a legitimate wait (the agent asked a question, or finished its turn)
    from a broken one (an LLM error / doom loop stranded the loop). Each
    ``_await_user_input`` call site declares its reason; the
    :attr:`is_external_wait` / :attr:`is_broken` views collapse the set to
    the distinctions most callers actually branch on.
    """

    # --- Healthy: the loop is parked by design, expected. ---
    ASK_USER = "ask_user"  # agent called ask_user — questions pending
    CREDENTIAL_FORM = "credential_form"  # agent called credentials(collect) — secure form pending
    COLONY_SUGGESTION = "colony_suggestion"  # a colony suggestion is pending
    TURN_DONE = "turn_done"  # finished a turn cleanly, awaiting next message
    AWAITING_QUEEN = "awaiting_queen"  # worker escalated, awaiting queen guidance
    USER_STOPPED = "user_stopped"  # user clicked Stop / cancelled the turn
    COLD_INTERRUPTED = "cold_interrupted"  # queen was mid-turn when runtime died; parked on reload
    # --- Broken: parked because something failed, not by design. ---
    LLM_ERROR = "llm_error"  # an LLM call failed; parked for the user
    EMPTY_RESPONSES = "empty_responses"  # repeated ghost / empty turns
    DOOM_LOOP = "doom_loop"  # tool doom-loop detected
    # --- Unknown: parked with no reason recorded — a bug if ever seen. ---
    UNKNOWN = "unknown"

    @property
    def is_external_wait(self) -> bool:
        """True when the park is correctly blocked on another party's input
        — a user question / colony suggestion, or a worker awaiting its
        queen. The idle nudge leaves these alone: there is genuinely
        nothing to nudge until that party responds."""
        return self in (
            ParkReason.ASK_USER,
            ParkReason.CREDENTIAL_FORM,
            ParkReason.COLONY_SUGGESTION,
            ParkReason.AWAITING_QUEEN,
        )

    @property
    def is_silent_park(self) -> bool:
        """True when the park is a clean stopping point that should not
        be auto-resumed — the agent finished its turn cleanly
        (TURN_DONE) or was explicitly stopped by the user
        (USER_STOPPED). The idle nudge leaves these alone: an
        auto-resume would override the user's natural pause. The agent
        restarts only on a real user message (``inject_event``).

        Distinct from :attr:`is_external_wait`: external-wait parks are
        blocked on a specific other party's input. Silent parks have no
        party to wait on — the agent is simply done for now.
        """
        return self in (
            ParkReason.TURN_DONE,
            ParkReason.USER_STOPPED,
            ParkReason.COLD_INTERRUPTED,
        )

    @property
    def is_broken(self) -> bool:
        """True for a park caused by a failure rather than by design —
        the loop is stranded and warrants quicker recovery."""
        return self in (
            ParkReason.LLM_ERROR,
            ParkReason.EMPTY_RESPONSES,
            ParkReason.DOOM_LOOP,
        )

    @property
    def activity(self) -> LoopActivity:
        """The :class:`LoopActivity` this park reason maps to — the single
        authoritative place a park reason becomes a top-level state.

        A deliberate end-of-turn park (the agent chose to stop and hand
        control off) is :attr:`~LoopActivity.AWAITING_USER`; every other
        park — broken, user-stopped, or unidentified — is
        :attr:`~LoopActivity.INTERRUPTED`. ``AWAITING_QUEEN`` is a worker
        that escalated by design, so it counts as a deliberate park.
        """
        if self in (
            ParkReason.ASK_USER,
            ParkReason.CREDENTIAL_FORM,
            ParkReason.COLONY_SUGGESTION,
            ParkReason.TURN_DONE,
            ParkReason.AWAITING_QUEEN,
            ParkReason.COLD_INTERRUPTED,
        ):
            return LoopActivity.AWAITING_USER
        # LLM_ERROR, EMPTY_RESPONSES, DOOM_LOOP, USER_STOPPED, UNKNOWN.
        return LoopActivity.INTERRUPTED


@dataclass
class LoopSignals:
    """Read-only snapshot of loop runtime state for non-lifecycle sources.

    Populated by the loop (via a ``signals_provider`` callback for the
    ticker, or built inline for a synchronous ``collect``) and handed to
    sources so they decide without poking at loop internals. Each source
    reads only the fields its point cares about — the idle fields are
    inert for :attr:`ReminderPoint.STREAM_STALLED` and vice versa.
    """

    # IDLE_TICK context.
    idle_seconds: float = 0.0
    awaiting_input: bool = False
    # Why the loop is parked, when it is — None when not parked. Granular
    # enough that the idle nudge can leave a legitimate question-park alone,
    # re-engage a broken park quickly, and nudge a normal idle one. See
    # :class:`ParkReason`; ``park_reason.is_question`` / ``.is_broken`` give
    # the coarse splits.
    park_reason: ParkReason | None = None
    # The loop's authoritative top-level state — for observability; the
    # idle nudge keys off park_reason, not this. None until first set.
    activity: LoopActivity | None = None
    # True after the user explicitly clicked Stop. The idle nudge leaves a
    # user-stopped agent alone — it resumes only on a message or chat re-entry.
    user_stopped: bool = False
    stream_active: bool = False
    first_event_seen: bool = False
    # STREAM_STALLED context — set only for that point's collect() call.
    stall_reason: str | None = None  # "ttft" | "inactive"
    stall_elapsed: float = 0.0


@dataclass
class ReminderContext:
    """Everything a source's ``render`` needs to decide.

    ``agent_ctx`` is the live :class:`AgentContext`; sources read what
    they need off it (``session_id``, ``agent_id``, …) — kept untyped
    here so this module stays dependency-free. ``signals`` is set only
    for temporal points.
    """

    point: ReminderPoint
    agent_ctx: Any
    signals: LoopSignals | None = None
    # Tool names executed in the batch this render rides — set only at
    # POST_TOOL_USE, so a source can tell what the agent just did (e.g.
    # distinguish a self-induced change from an external one).
    tool_names: list[str] | None = None


@dataclass
class Reminder:
    """A rendered reminder, with enough metadata for the loop to place it.

    Sources may return a bare ``str`` instead — the hub normalizes it to
    a default ``Reminder``. Every reminder is treated uniformly: injected
    wrapped in a ``<system-reminder>`` block and tagged ``is_system_reminder``
    on the conversation message, and a drained reminder energizes a turn (it
    breaks a pending-input wait) so it is always acted upon rather than left
    to rot unread in a parked conversation.
    """

    body: str
    source: str = "reminder"
    placement: Placement = Placement.USER_MESSAGE
    meta: dict[str, Any] = field(default_factory=dict)


class ReminderSource:
    """Base class for a producer of reminders.

    Subclasses declare which points they fire at (``points``), optionally
    observe each turn (``observe_turn``), optionally declare a polling
    cadence for temporal points (``tick_interval``), and render a body
    (``render``). A bare-string body carries no ``<system-reminder>``
    wrapper — the hub adds it.
    """

    name: str = "reminder"

    # Whether a body from this source should WAKE a loop that is about to park.
    # Off by default: most reminders are context the agent reads on its next
    # turn, and a parked queen is parked because the user's move is genuinely
    # next. Opt in only when the reminder asks for an action the user cannot
    # supply, and which would otherwise rot unread until they happen to speak
    # again — see ``CrmRevealReminderSource``, where the user has no way to
    # proceed precisely because the agent has not acted yet.
    energizes: bool = False

    def points(self) -> set[ReminderPoint]:
        raise NotImplementedError

    def applies_to(self, agent_ctx: Any) -> bool:
        """Whether this source is relevant to the agent running the loop.

        Evaluated once per session by :meth:`ReminderHub.bind`. A source
        that returns False is skipped entirely — never observed, never
        rendered, never polled. This is how one shared agent loop serves
        many agent roles: each source self-declares where it belongs
        rather than the loop being configured per agent. Default: applies
        to every agent.
        """
        return True

    def observe_turn(self, tool_names: list[str]) -> None:
        """Per-turn observation tick — not an injection.

        Called once per outer turn so stateful sources can advance
        counters. Default: no-op.
        """

    def tick_interval(self) -> float | None:
        """Polling cadence (seconds) for temporal points, or None.

        A source that fires at :attr:`ReminderPoint.IDLE_TICK` returns
        the interval at which the hub's ticker should consult it. The
        hub polls at the minimum interval across all sources. Sources
        with only lifecycle points return None (the default).
        """
        return None

    async def render(self, rctx: ReminderContext) -> str | Reminder | None:
        """Return the reminder for ``rctx.point``, or None.

        May return a bare ``str`` (wrapped by the hub) or a fully-formed
        :class:`Reminder` when the source needs to control placement /
        the system-nudge flag.
        """
        raise NotImplementedError


_FOOTER = "Only act on this if relevant to the current work. NEVER mention this reminder to the user."


def wrap_reminder(bodies: list[str]) -> str:
    """Wrap one or more source bodies in a single ``<system-reminder>``.

    Returns ``""`` when there's nothing to show.
    """
    joined = "\n\n".join(b.strip() for b in bodies if b and b.strip())
    if not joined:
        return ""
    return f"<system-reminder>\n{joined}\n\n{_FOOTER}\n</system-reminder>"


class ReminderHub:
    """Registry + fan-out for reminder sources.

    Lives on the AgentLoop. The loop calls :meth:`observe_turn` once per
    turn and :meth:`fire` at each lifecycle point. For temporal points it
    calls :meth:`start` once (which spins up a background ticker if any
    source declares a ``tick_interval``) and drains :meth:`take_pending`
    at its iteration boundary. All fan-out is best-effort — a misbehaving
    source is logged and skipped, never propagated.
    """

    def __init__(self) -> None:
        self._sources: list[ReminderSource] = []
        # Sources that apply to the bound agent (see bind()). None until
        # bind() runs — before that, every registered source is consulted.
        self._active: list[ReminderSource] | None = None
        # Reminders parked by the temporal ticker, awaiting loop drain.
        self._pending: list[Reminder] = []
        self._ticker_task: asyncio.Task[None] | None = None

    def register(self, source: ReminderSource) -> None:
        self._sources.append(source)

    def bind(self, agent_ctx: Any) -> None:
        """Resolve which sources apply to this agent — once per session.

        Called by the loop before it consults the hub. From here on,
        observe_turn / collect / the ticker fan out only to the
        applicable subset. A source whose ``applies_to`` raises is kept
        (fail-open — a broken filter shouldn't silently drop reminders).
        """
        active: list[ReminderSource] = []
        for s in self._sources:
            try:
                ok = s.applies_to(agent_ctx)
            except Exception:
                logger.debug("reminder source %s applies_to failed; keeping it", s.name, exc_info=True)
                ok = True
            if ok:
                active.append(s)
        self._active = active

    def _consulted(self) -> list[ReminderSource]:
        """Sources to fan out to: the bound subset, or all if not bound."""
        return self._active if self._active is not None else self._sources

    def observe_turn(self, tool_names: list[str]) -> None:
        for s in self._consulted():
            try:
                s.observe_turn(tool_names)
            except Exception:
                logger.debug("reminder source %s observe_turn failed", s.name, exc_info=True)

    async def collect(
        self,
        point: ReminderPoint,
        agent_ctx: Any,
        signals: LoopSignals | None = None,
        tool_names: list[str] | None = None,
    ) -> list[Reminder]:
        """Consult every source firing at ``point`` → list of Reminders.

        Bare-string source bodies are normalized to a default
        :class:`Reminder`. Empty bodies are dropped. ``tool_names`` carries
        the batch's executed tools at POST_TOOL_USE.
        """
        rctx = ReminderContext(point=point, agent_ctx=agent_ctx, signals=signals, tool_names=tool_names)
        out: list[Reminder] = []
        for s in self._consulted():
            try:
                if point not in s.points():
                    continue
                res = await s.render(rctx)
            except Exception:
                logger.debug("reminder source %s render failed at %s", s.name, point, exc_info=True)
                continue
            if res is None:
                continue
            if isinstance(res, str):
                res = Reminder(body=res, source=s.name)
            if res.body and res.body.strip():
                # Stamp the source's wake policy so a caller that merges
                # bodies (fire()) can still tell whether any contributor
                # wants the loop woken. setdefault: a source that built its
                # own Reminder may already have decided per-render.
                res.meta.setdefault("energizes", s.energizes)
                out.append(res)
        return out

    async def fire(
        self,
        point: ReminderPoint,
        agent_ctx: Any,
        tool_names: list[str] | None = None,
    ) -> str | None:
        """Collect every source's body for ``point`` → one wrapped block, or None.

        Back-compat entry point for lifecycle points: the loop places the
        returned ``<system-reminder>`` block itself. Temporal points should
        use :meth:`collect` instead. ``tool_names`` carries the batch's
        executed tools at POST_TOOL_USE.
        """
        block, _ = await self.fire_energized(point, agent_ctx, tool_names=tool_names)
        return block

    async def fire_energized(
        self,
        point: ReminderPoint,
        agent_ctx: Any,
        tool_names: list[str] | None = None,
    ) -> tuple[str | None, bool]:
        """:meth:`fire`, plus whether any contributing source wants the loop woken.

        Split out because ``fire`` merges every source into one block and so
        loses which of them produced it — and "should this wake a parked
        agent?" is a per-source policy (:attr:`ReminderSource.energizes`).
        """
        items = await self.collect(point, agent_ctx, tool_names=tool_names)
        block = wrap_reminder([r.body for r in items]) or None
        energized = bool(block) and any(r.meta.get("energizes") for r in items)
        return block, energized

    # ----- temporal ticker -------------------------------------------------

    def _min_tick_interval(self) -> float | None:
        """Tightest polling cadence across sources, or None if none poll."""
        hints = [iv for s in self._consulted() if (iv := s.tick_interval()) is not None and iv > 0]
        return min(hints) if hints else None

    async def start(
        self,
        agent_ctx: Any,
        *,
        signals_provider: Callable[[], LoopSignals] | None = None,
        wake: Callable[[], None] | None = None,
    ) -> None:
        """Start the temporal ticker if any source declares a cadence.

        ``signals_provider`` is called each tick to snapshot loop runtime
        state; ``wake`` (if given) is called after a tick parks at least
        one reminder, so a loop blocked on its input event re-checks.
        No-op when there are no temporal sources, or if already started.
        """
        if self._ticker_task is not None:
            return
        interval = self._min_tick_interval()
        if interval is None:
            return
        self._ticker_task = asyncio.create_task(
            self._run_ticker(interval, agent_ctx, signals_provider, wake),
            name="reminder_ticker",
        )

    async def stop(self) -> None:
        """Cancel the temporal ticker and drop any undrained reminders."""
        if self._ticker_task is not None and not self._ticker_task.done():
            self._ticker_task.cancel()
            try:
                await self._ticker_task
            except BaseException:  # noqa: BLE001 - cancellation / already-logged
                pass
        self._ticker_task = None
        self._pending.clear()

    async def _run_ticker(
        self,
        interval: float,
        agent_ctx: Any,
        signals_provider: Callable[[], LoopSignals] | None,
        wake: Callable[[], None] | None,
    ) -> None:
        """Poll loop: consult IDLE_TICK sources, park what they produce."""
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return
            try:
                signals = signals_provider() if signals_provider is not None else None
                items = await self.collect(ReminderPoint.IDLE_TICK, agent_ctx, signals=signals)
                if items:
                    self._pending.extend(items)
                    if wake is not None:
                        wake()
            except Exception:
                logger.debug("reminder ticker tick failed", exc_info=True)

    def post(self, reminder: Reminder) -> None:
        """Park a reminder produced *reactively* — neither by the ticker
        nor at a lifecycle point, but because something just happened
        (e.g. the per-turn tool-call budget was reached).

        Lands in the same buffer the ticker uses, so the loop drains it
        via :meth:`take_pending` at its next iteration boundary — on the
        loop coroutine, with no conversation-write race.
        """
        self._pending.append(reminder)

    def take_pending(self) -> list[Reminder]:
        """Hand off reminders parked by the ticker / :meth:`post`; clears
        the buffer.

        Called by the loop on its own coroutine at the iteration
        boundary, so the resulting conversation writes never race the
        loop's own mutations.
        """
        out = self._pending
        self._pending = []
        return out
