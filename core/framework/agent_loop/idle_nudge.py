"""Idle-nudge reminder source.

A :class:`ReminderSource` for the temporal :class:`ReminderPoint.IDLE_TICK`.
It complements the stream-level TTFT/inter-event watchdog inside
``_run_turn_loop`` — which only fires while a stream task is alive —
by nudging the model when the *session* sits quiet:

  * **between_turns** — no stream task at all (the loop is idle between
    iterations: judge work, setup, or genuinely parked).
  * **slow_ttft** — a stream is open but no first event has arrived yet.
  * **parked_no_question** — a questionless park with NO open work and an
    unidentified reason (``UNKNOWN``). Nudge **once** to find the next
    step, then wait for the user. A ``TURN_DONE`` park with no open work
    is *not* nudged at all — a turn that finished cleanly is genuinely
    idle, nothing to do.
  * **parked_open_tasks** — a questionless park whose task list still has
    open tasks: the nudge names them and pushes the agent to finish. Fires
    up to the full cap for an ``UNKNOWN`` park, but exactly **once** for a
    ``TURN_DONE`` one (resume the queued work, then leave it to the user).
  * **parked_broken** — the loop parked after a *failure* (LLM error, tool
    doom loop, repeated empty turns), not by design. Recovered on a shorter
    budget, up to the full cap — a stranded loop should be re-engaged fast.

The park substate is chosen from the loop's
:class:`~framework.agent_loop.reminders.ParkReason`. A stream that is
actively producing events is left alone: the stream-level inter-event
watchdog owns that case. A park correctly blocked on another party — an
ask_user question / colony suggestion, or a worker awaiting its queen —
is left alone too (``ParkReason.is_external_wait``).

Per-variant caps bound the nudging; they re-arm via :meth:`reset` when the
user sends a message (the loop calls it), so a cap is "per user-response
cycle", not "per whole session".

All policy lives here, mirroring how ``framework.tasks.reminders`` keeps
task-reminder policy in one module. The loop owns only the runtime snapshot
(:class:`~framework.agent_loop.reminders.LoopSignals`) handed in via
``ReminderContext.signals``.
"""

from __future__ import annotations

import logging
import time

from framework.agent_loop.reminders import (
    ParkReason,
    Reminder,
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)


def _sentinel_autopilot_active(agent_ctx: object) -> bool:
    """True when Sentinel's escalation source owns this colony queen's parks.

    Best-effort: any failure returns False so a glitch never silences the
    idle nudge.
    """
    try:
        if not getattr(agent_ctx, "is_queen_stream", False):
            return False
        colony_id = getattr(agent_ctx, "colony_id", None)
        if not colony_id:
            return False
        from framework.sentinel import store

        return store.load_notifications_config(colony_id).sentinel_enabled
    except Exception:
        return False


async def _open_tasks(agent_ctx: object) -> list:
    """Open (not-completed) tasks for the session's task list.

    Best-effort — any failure (no session_id, store error) returns ``[]`` so a
    lookup glitch never changes which nudge variant fires.
    """
    session_id = getattr(agent_ctx, "session_id", None)
    if not session_id:
        return []
    try:
        from framework.tasks import get_task_store
        from framework.tasks.models import TaskStatus

        records = await get_task_store().list_tasks(session_id)
    except Exception:
        logger.debug("idle_nudge: open-task lookup failed", exc_info=True)
        return []
    # "Open" = active and unfinished. Archived tasks are parked in History,
    # not the working plan — counting them (they're != completed) as open
    # would keep the idle nudge firing after the plan is actually clear.
    return [r for r in (records or []) if r.status not in (TaskStatus.COMPLETED, TaskStatus.ARCHIVED)]


async def _session_goal(agent_ctx: object) -> str | None:
    """Anchor goal for the session's task list, or None if absent.

    Best-effort — any lookup failure returns None so the nudge body's
    goal-prefix degrades silently instead of changing fire decisions.
    """
    session_id = getattr(agent_ctx, "session_id", None)
    if not session_id:
        return None
    try:
        from framework.tasks import get_task_store

        meta = await get_task_store().get_meta(session_id)
        return meta.goal if meta is not None else None
    except Exception:
        logger.debug("idle_nudge: goal lookup failed", exc_info=True)
        return None


def _name_tasks(tasks: list, limit: int = 5) -> str:
    """A short ``#id "subject"`` list of up to ``limit`` tasks."""
    shown = tasks[:limit]
    parts = []
    for t in shown:
        subject = (getattr(t, "subject", "") or "").strip()
        tid = getattr(t, "id", "?")
        parts.append(f'#{tid} "{subject}"' if subject else f"#{tid}")
    rest = len(tasks) - len(shown)
    joined = ", ".join(parts)
    return f"{joined} (+{rest} more)" if rest > 0 else joined


class IdleNudgeSource(ReminderSource):
    """Nudge the model when the session has been idle past the budget.

    Fires only at :attr:`ReminderPoint.IDLE_TICK`. Per-variant caps keep a
    wedged session from being nudged forever; the self-rate-limit keeps a
    single stall from spending a whole cap at once (the ticker can poll
    several times before the loop drains what was parked).

    Three independently-configurable budgets, keyed off the park's
    :class:`~framework.agent_loop.reminders.ParkReason`:

      * **general** — ``between_turns`` / ``slow_ttft`` stalls.
      * **awaiting** — a questionless park (``TURN_DONE`` / ``UNKNOWN``).
        Defaults to the same generous value as the general budget — a
        shorter one once fired while a user was still composing a message.
      * **broken** — a park caused by a failure (``LLM_ERROR`` /
        ``DOOM_LOOP`` / ``EMPTY_RESPONSES``). Shorter: a stranded loop
        warrants quicker recovery, with no "user mid-typing" risk.
    """

    name = "idle_nudge"

    def __init__(
        self,
        *,
        budget_seconds: float,
        max_nudges: int,
        awaiting_budget_seconds: float = 0.0,
        broken_budget_seconds: float = 0.0,
    ) -> None:
        self._budget = budget_seconds
        self._awaiting_budget = awaiting_budget_seconds
        self._broken_budget = broken_budget_seconds
        self._cap = max_nudges
        # Per-substate nudge counts; re-armed by reset() on a user message.
        self._nudges: dict[str, int] = {}
        # Monotonic time of the last park *evaluation* that passed the budget
        # gate (0.0 = none yet). Throttles both firing and the task-store
        # lookup below to once per budget window. Keyed on evaluation time,
        # not last-fire, so a park that has hit its nudge cap (and so never
        # fires again) still stops re-scanning the task store every poll tick.
        self._last_eval_at = 0.0
        # Signature of the last gate-suppression line logged, so a steady
        # parked state logs once instead of once per poll tick (see _gate).
        self._last_gate_sig: str | None = None

    def _enabled(self) -> bool:
        return self._cap > 0 and (self._budget > 0 or self._awaiting_budget > 0 or self._broken_budget > 0)

    def _cap_for(self, substate: str, reason: ParkReason | None) -> int:
        """Per-variant cap (nudges per user-response cycle).

        * ``parked_no_question`` — a questionless park with nothing queued
          is nudged exactly **once**; if the agent still finds no step,
          stop and wait for the user.
        * ``parked_open_tasks`` from a ``TURN_DONE`` park — a turn that
          finished cleanly while work was still queued is nudged **once**
          to resume it, then left for the user.
        * everything else (open tasks from a non-TURN_DONE park, a broken
          park, between-turns / slow-TTFT stalls) gets the full
          ``max_nudges`` budget so a recoverable stall keeps being
          re-engaged."""
        if substate == "parked_no_question":
            return 1
        if substate == "parked_open_tasks" and reason == ParkReason.TURN_DONE:
            return 1
        return self._cap

    def reset(self) -> None:
        """Re-arm every variant's nudge budget.

        Called by the loop when the user sends a message, so a cap is
        "per user-response cycle", not "per whole session" — after the user
        replies, each variant may nudge afresh.
        """
        self._nudges.clear()
        self._last_eval_at = 0.0
        self._last_gate_sig = None

    def _gate(self, signature: str, msg: str, *args: object) -> None:
        """Log a gate-suppression decision at INFO, but only once per state.

        The idle ticker polls every few seconds; without this every parked
        tick would repeat the same "suppressed" line forever (only the idle
        seconds change). ``signature`` is the state key with the volatile
        idle-seconds excluded, so a steady gate logs exactly once and
        re-logs only when the gate actually changes. Producing a nudge and
        ``reset()`` both clear the tracker so the next gate logs afresh.
        """
        if signature == self._last_gate_sig:
            return
        self._last_gate_sig = signature
        logger.info(msg, *args)

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.IDLE_TICK}

    def tick_interval(self) -> float | None:
        if not self._enabled():
            return None
        # Poll at most every 5s, never below 10ms — production budgets
        # (>=2s) collapse to ``budget/2``; tiny test budgets need a finer
        # cadence. Key off the smallest active budget so the fastest path
        # is still polled finely enough.
        budgets = [b for b in (self._budget, self._awaiting_budget, self._broken_budget) if b > 0]
        return max(0.01, min(5.0, min(budgets) / 2))

    async def render(self, rctx: ReminderContext) -> Reminder | None:
        if not self._enabled():
            return None
        sig = rctx.signals
        if sig is None:
            return None
        # Sentinel autopilot owns the parked-queen decision (nudge/escalate)
        # when enabled for this colony queen — defer so the two never
        # double-nudge. Checked per-tick so a mid-session toggle takes effect.
        if _sentinel_autopilot_active(rctx.agent_ctx):
            return None
        # The user explicitly clicked Stop — never auto-resume the agent.
        # It restarts only on a message or chat re-entry, by design.
        if sig.user_stopped:
            if sig.awaiting_input:
                self._gate(
                    "user_stopped",
                    "[idle_nudge] gate=user_stopped — explicit Stop, suppressed (idle=%.0fs)",
                    sig.idle_seconds,
                )
            return None

        # Diagnose which sub-state is idle, and pick the budget for it.
        # ``reason`` is None for the non-parked stalls (between_turns /
        # slow_ttft); the awaiting branch narrows it to a concrete value.
        reason: ParkReason | None = sig.park_reason
        if sig.awaiting_input:
            reason = sig.park_reason or ParkReason.UNKNOWN
            # A park correctly blocked on another party (a user question /
            # colony suggestion, or a worker awaiting its queen) is
            # legitimate — nothing to nudge until that party responds.
            if reason.is_external_wait:
                self._gate(
                    f"external_wait:{reason}",
                    "[idle_nudge] gate=external_wait — parked awaiting another party (%s), suppressed (idle=%.0fs)",
                    reason,
                    sig.idle_seconds,
                )
                return None
            # A clean end-of-turn park (or a USER_STOPPED park, though
            # the boolean gate above already caught that) is the user's
            # natural stopping point — auto-resuming would override
            # their pause. Wait for a real user message instead.
            if reason.is_silent_park:
                self._gate(
                    f"silent_park:{reason}",
                    "[idle_nudge] gate=silent_park — clean stopping point (%s), suppressed (idle=%.0fs)",
                    reason,
                    sig.idle_seconds,
                )
                return None
            if reason.is_broken:
                # A failure stranded the loop — recover it on the shorter
                # broken budget rather than the questionless one.
                if self._broken_budget <= 0:
                    self._gate(
                        f"no_broken_budget:{reason}",
                        "[idle_nudge] gate=no_broken_budget — broken park (%s) but the broken budget is disabled (idle=%.0fs)",
                        reason,
                        sig.idle_seconds,
                    )
                    return None
                substate = "parked_broken"
                budget = self._broken_budget
            else:
                # UNKNOWN only — a questionless park with no recorded
                # reason. Treated as broken-ish (we don't know if it's
                # safe to ignore) so the awaiting budget still fires for
                # recovery. If a real ParkReason is added later, classify
                # it explicitly above rather than letting it default here.
                if self._awaiting_budget <= 0:
                    self._gate(
                        "no_awaiting_budget",
                        "[idle_nudge] gate=no_awaiting_budget — questionless park but the awaiting budget is disabled (idle=%.0fs)",
                        sig.idle_seconds,
                    )
                    return None
                substate = "parked_no_question"
                budget = self._awaiting_budget
        elif not sig.stream_active:
            substate = "between_turns"
            budget = self._budget
        elif not sig.first_event_seen:
            substate = "slow_ttft"
            budget = self._budget
        else:
            # Stream is producing events — the stream-level inter-event
            # watchdog owns this case. Don't double-nudge.
            return None
        if budget <= 0 or sig.idle_seconds < budget:
            if sig.awaiting_input and budget > 0:
                logger.debug(
                    "[idle_nudge] gate=under_budget — parked questionless %.0fs/%.0fs",
                    sig.idle_seconds,
                    budget,
                )
            return None
        now = time.monotonic()
        # Self-rate-limit independent of the loop clock: the ticker may poll
        # several times within one budget window before the loop drains the
        # parked nudge — without this a single stall would spend the whole
        # cap at once. Crucially this ALSO throttles the (blocking, thread-pool)
        # task-store lookup below to at most once per budget window, including
        # for a park that has already hit its nudge cap: a fire-keyed throttle
        # would freeze once nudges stop firing and let the lookup re-scan the
        # filesystem on every ~5s tick, starving the shared executor.
        if self._last_eval_at and (now - self._last_eval_at) < budget:
            if sig.awaiting_input:
                logger.debug(
                    "[idle_nudge] gate=rate_limited — last eval %.0fs ago < %.0fs",
                    now - self._last_eval_at,
                    budget,
                )
            return None
        self._last_eval_at = now

        # A questionless park splits by whether the task list has open work:
        #   parked_open_tasks   — open tasks; push the agent to finish them.
        #   parked_no_question  — nothing queued; nudge once to find a step.
        # A TURN_DONE park (a turn that finished cleanly) is nudged ONLY
        # when it still has open tasks — a truly-done queen with an empty
        # list is genuinely idle, so leave it alone entirely.
        open_tasks: list = []
        if substate == "parked_no_question":
            open_tasks = await _open_tasks(rctx.agent_ctx)
            if open_tasks:
                substate = "parked_open_tasks"
            elif reason == ParkReason.TURN_DONE:
                self._gate(
                    "turn_done_idle",
                    "[idle_nudge] gate=turn_done_idle — turn finished cleanly with no open tasks, nothing to nudge (idle=%.0fs)",
                    sig.idle_seconds,
                )
                return None
            else:
                logger.debug(
                    "[idle_nudge] parked questionless: session_id=%r open_tasks=0 → parked_no_question (idle=%.0fs)",
                    getattr(rctx.agent_ctx, "session_id", None),
                    sig.idle_seconds,
                )

        cap = self._cap_for(substate, reason)
        count = self._nudges.get(substate, 0)
        if count >= cap:
            if sig.awaiting_input:
                self._gate(
                    f"cap_reached:{substate}",
                    "[idle_nudge] gate=cap_reached — substate=%s count=%d/%d, re-arms on the next user message",
                    substate,
                    count,
                    cap,
                )
            return None

        count += 1
        self._nudges[substate] = count
        # (``_last_eval_at`` was already stamped at the budget gate above, so
        # the next tick within this window is rate-limited the same way.)
        # A nudge is firing — clear the gate tracker so a later suppression
        # (e.g. cap_reached on the next window) logs once more rather than
        # being deduped against a stale pre-nudge gate.
        self._last_gate_sig = None

        # Only fetch the goal for the open-tasks variant — that's the
        # only nudge whose body uses it. Avoids an unnecessary store
        # roundtrip on the broken / no-question / between-turns paths.
        goal = await _session_goal(rctx.agent_ctx) if substate == "parked_open_tasks" else None
        body = self._body(substate, sig.idle_seconds, open_tasks, sig.park_reason, goal=goal)
        logger.info(
            "[idle_nudge] producing nudge (substate=%s, count=%d/%d, idle=%.0fs)",
            substate,
            count,
            cap,
            sig.idle_seconds,
        )
        return Reminder(
            body=body,
            source=self.name,
            meta={
                "idle_seconds": sig.idle_seconds,
                "substate": substate,
                "nudge_count": count,
                "cap": cap,
            },
        )

    def _body(
        self,
        substate: str,
        idle_seconds: float,
        open_tasks: list,
        park_reason: ParkReason | None,
        *,
        goal: str | None = None,
    ) -> str:
        if substate == "parked_broken":
            reason = park_reason or ParkReason.UNKNOWN
            if reason == ParkReason.DOOM_LOOP:
                # A doom-loop park is the OPPOSITE of a transient failure:
                # the breaker blocked a call *because* it was being repeated.
                # Telling the agent to "re-attempt the work that failed" here
                # would re-issue the blocked call and feed the loop the breaker
                # just stopped — so steer it to a different approach instead,
                # mirroring the breaker's own injected guidance.
                return (
                    f"The agent loop parked {idle_seconds:.0f}s ago after a tool "
                    "doom-loop — the same call was issued repeatedly with "
                    "identical arguments, so the breaker blocked it. Do NOT "
                    "repeat that call; that is what tripped the breaker. Recover "
                    "with a DIFFERENT approach (different arguments, a different "
                    "tool, or a text-only step), or stop and report what you "
                    "already have. Do NOT block on the user unless you genuinely "
                    "need an answer to proceed."
                )
            return (
                f"The agent loop parked {idle_seconds:.0f}s ago after a failure "
                f"({reason.value}) — this is not a normal wait for the user. "
                "Recover now: re-attempt the work that failed, or take the next "
                "concrete step from the conversation above. Do NOT block on the "
                "user unless you genuinely need an answer to proceed."
            )
        if substate == "parked_open_tasks":
            # Prepend the goal so the queen re-engages with the anchor in
            # view. If the user's next message is a real pivot (work that
            # falls outside this goal), seeing it here lets the queen
            # recognise it without round-tripping through task_list.
            goal_prefix = f"Your goal: {goal}. " if goal else ""
            return (
                f"{goal_prefix}You have been parked awaiting user input for "
                f"{idle_seconds:.0f}s with no pending question, and your task "
                f"list still has open work: {_name_tasks(open_tasks)}. Resume "
                "now and finish those open tasks. Only block on the user via "
                "ask_user if a task genuinely needs their answer."
            )
        if substate == "parked_no_question":
            return (
                f"You have been parked awaiting user input for {idle_seconds:.0f}s, "
                "but you asked no question — there is nothing for the user to "
                "answer. Continue now: take the next concrete step on your work. "
                "Only block on the user via a proper question tool (ask_user) if "
                "you genuinely need an answer to proceed."
            )
        return (
            f"The session has been idle for {idle_seconds:.0f}s ({substate}) with "
            "no progress and no pending user input. Pick the next concrete step "
            "from the conversation above and take it. Do NOT ask the user a "
            "question unless absolutely necessary — prefer acting on "
            "already-available information."
        )
