"""Sentinel's decision engine — a temporal :class:`ReminderSource`.

For a colony queen whose colony has opted in, this owns the parked-queen
decision the plain idle-nudge can't make: when the goal is *not* done and the
queen has stalled, choose between

  * **nudge** — return a :class:`Reminder`, which breaks the pending-input
    wait and pushes the queen to keep working autonomously;
  * **escalate** — message the human via Sentinel's manager and return
    ``None`` so the queen stays parked until they reply;
  * **nothing** — goal complete, a sacred stop, or a human is watching.

A returned reminder wakes the loop; doing I/O and returning ``None`` keeps it
parked. That single contract (see ``reminders.Reminder``) is what lets one
source express both outcomes.

When autopilot is enabled for a colony queen this source *owns* its park
decisions; :class:`~framework.agent_loop.idle_nudge.IdleNudgeSource` self-skips
that case so the two never double-nudge.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from framework.agent_loop.reminders import (
    ParkReason,
    Reminder,
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)
from framework.sentinel import notifier, store, token
from framework.sentinel.classifier import (
    ClassifierVerdict,
    ParkContext,
    classify_park,
    format_running_workers,
)

logger = logging.getLogger(__name__)

# Parks we never act on: explicit user pause, a colony-fork suggestion (can't
# be answered by a text reply), or a worker waiting on its queen.
_SKIP_REASONS = frozenset({ParkReason.USER_STOPPED, ParkReason.COLONY_SUGGESTION, ParkReason.AWAITING_QUEEN})

# Report kinds — every Sentinel evaluation produces one (the manager picks the
# message template + framing from this; the desktop decides notify-vs-feed):
#   blocker   → a genuine block (broken park, or classifier says needs_human):
#               "your colony needs you" + the question. Parks for a reply.
#   heartbeat → auto-continued for max_nudges cycles: a louder checkpoint the
#               human can redirect or ack. Parks.
#   done      → the judge says the goal is COMPLETE: a completion report. Parks
#               (terminal) but needs no reply.
#   progress  → the judge says "keep going": an FYI of what the colony is doing,
#               plus an internal nudge. Inbox-feed only (never telegram/slack),
#               no notification.
ESCALATE_BLOCKER = "blocker"
ESCALATE_HEARTBEAT = "heartbeat"
REPORT_DONE = "done"
REPORT_PROGRESS = "progress"
# Only "progress" keeps the colony moving (a nudge); every other kind parks and
# holds the source until the next real resume.


class EscalationSource(ReminderSource):
    name = "sentinel_escalation"

    def __init__(
        self,
        *,
        park_context_provider: Callable[[], Awaitable[ParkContext]],
        on_escalate: Callable[[dict[str, Any]], bool] | None = None,
        has_attached_ui: Callable[[str], bool] | None = None,
        classify_fn: Callable[[ParkContext, Any], Awaitable[ClassifierVerdict]] | None = None,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._park_context_provider = park_context_provider
        self._on_escalate = on_escalate
        self._has_attached_ui = has_attached_ui
        self._classify_fn = classify_fn or classify_park
        self._now = now_fn or time.monotonic
        # Per-park-cycle state, re-armed by reset() on a real resume.
        self._held = False  # a blocker/done/heartbeat is out — stop evaluating
        self._nudge_count = 0
        self._last_eval_at = 0.0
        # (kind, summary) of the last report emitted — collapses identical
        # consecutive reports so a steady colony doesn't repeat itself.
        self._last_report_sig: tuple[str, str] | None = None
        # One-shot diagnostic latch (see applies_to): logs the gate inputs the
        # first time the hub checks this stream, so a "sentinel never fired"
        # report shows WHY at the applies_to layer (which is otherwise silent).
        self._gate_logged = False

    # ----- ReminderSource contract ----------------------------------------

    def applies_to(self, agent_ctx: Any) -> bool:
        # Queen/overseer only (workers have is_queen_stream False), and only
        # once a colony is bound — a DM queen has no per-colony config and so
        # is off by default.
        is_queen = bool(getattr(agent_ctx, "is_queen_stream", False))
        colony_id = getattr(agent_ctx, "colony_id", None)
        if not self._gate_logged:
            self._gate_logged = True
            try:
                opted = bool(store.load_notifications_config(colony_id).sentinel_enabled) if colony_id else False
            except Exception:
                opted = False
            logger.debug(
                "[sentinel] applies_to: is_queen_stream=%s colony_id=%r opted_in=%s (stream_id=%r) — sentinel %s this stream",
                is_queen,
                colony_id,
                opted,
                getattr(agent_ctx, "stream_id", None),
                "OWNS" if (is_queen and colony_id) else "SKIPS",
            )
        if not is_queen:
            return False
        return bool(colony_id)

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.IDLE_TICK}

    def tick_interval(self) -> float | None:
        # Coarse on purpose: the budget (classify_after_seconds, ~5 min) is
        # enforced in render() against idle_seconds, so polling resolution can
        # be loose. A ~60s cap keeps the shared hub ticker from tightening for
        # every colony queen; the per-colony enable check in render() is what
        # actually gates work.
        return max(5.0, min(60.0, store.classify_after_seconds() / 2))

    def reset(self) -> None:
        """Re-arm on a real resume (the loop calls this from inject_event)."""
        self._held = False
        self._nudge_count = 0
        self._last_eval_at = 0.0
        self._last_report_sig = None

    # ----- decision -------------------------------------------------------

    async def render(self, rctx: ReminderContext) -> Reminder | None:
        sig = rctx.signals
        if sig is None or not sig.awaiting_input or sig.user_stopped:
            return None
        reason = sig.park_reason or ParkReason.UNKNOWN
        if reason in _SKIP_REASONS:
            return None

        agent_ctx = rctx.agent_ctx
        colony_id = getattr(agent_ctx, "colony_id", None)
        session_id = getattr(agent_ctx, "session_id", None)
        if not colony_id or not session_id:
            return None

        cfg = store.load_notifications_config(colony_id)
        if not cfg.sentinel_enabled:
            logger.debug(
                "[sentinel] no-escalate (colony=%s): not opted in (sentinel_enabled=False, channel=%s)",
                colony_id,
                cfg.channel,
            )
            return None

        # Per-colony idle budget overrides the global default when set.
        budget = cfg.classify_after_seconds or store.classify_after_seconds()
        if sig.idle_seconds < budget:
            logger.debug(
                "[sentinel] waiting (colony=%s): idle %.0fs < budget %.0fs",
                colony_id,
                sig.idle_seconds,
                budget,
            )
            return None

        # Self-rate-limit: the ticker can poll several times per window before
        # the loop drains what we parked — evaluate at most once per window.
        now = self._now()
        if self._last_eval_at and (now - self._last_eval_at) < budget:
            logger.debug(
                "[sentinel] rate-limited (colony=%s): last evaluated %.0fs ago (< %.0fs)",
                colony_id,
                now - self._last_eval_at,
                budget,
            )
            return None
        self._last_eval_at = now
        logger.debug(
            "[sentinel] evaluating (colony=%s idle=%.0fs reason=%s)",
            colony_id,
            sig.idle_seconds,
            reason.value,
        )

        # A blocker/done/heartbeat is already out — stop evaluating until resume.
        if self._held:
            logger.debug("[sentinel] holding (colony=%s): report already out", colony_id)
            return None

        try:
            pctx = await self._park_context_provider()
        except Exception:
            logger.debug("sentinel: park-context provider failed", exc_info=True)
            return None

        # No goal AND no open tasks is the one "nothing to act on" case — there
        # is no real work context to report on. With a goal or tasks present
        # there is always something to tell the human (blocker/progress/done).
        if not pctx.goal and not pctx.open_tasks:
            logger.debug(
                "[sentinel] nothing to report (colony=%s): no goal and no open tasks",
                colony_id,
            )
            return None

        kind = await self._decide(reason, pctx, getattr(agent_ctx, "llm", None))
        # A None kind means "can't decide this cycle" (classifier glitch) — do
        # NOT manufacture a nudge or an escalation. Re-evaluate next window; the
        # budget gate above already stamped _last_eval_at so we wait a full one.
        if kind is None:
            logger.info(
                "[sentinel] no-op (colony=%s): classifier unavailable/errored, not nudging a parked queen",
                colony_id,
            )
            return None
        self._report(colony_id, session_id, reason, pctx, cfg, kind)

        # Only "progress" keeps the colony moving — wake the queen.
        if kind == REPORT_PROGRESS:
            self._nudge_count += 1
            logger.info(
                "[sentinel] nudge (colony=%s count=%d idle=%.0fs)",
                colony_id,
                self._nudge_count,
                sig.idle_seconds,
            )
            return Reminder(
                body=self._nudge_body(pctx),
                source=self.name,
                meta={"substate": "sentinel_nudge", "nudge_count": self._nudge_count},
            )
        return None

    async def _decide(self, reason: ParkReason, pctx: ParkContext, llm: Any) -> str | None:
        """Pick this evaluation's report kind, or ``None`` to no-op this cycle."""
        if reason.is_broken or pctx.hard_blocker:
            return ESCALATE_BLOCKER
        # Auto-continued for max_nudges cycles — stop nudging, surface a louder
        # checkpoint for the human to redirect or ack.
        if self._nudge_count >= store.max_nudges_before_escalate():
            return ESCALATE_HEARTBEAT
        # Loop-breaker: a clean turn-end with no open tasks that we have ALREADY
        # nudged once is not producing new work — each nudge just gets the same
        # "I'm done / idle" restatement (the observed InMail loop). Stop nudging
        # and surface a single heartbeat the human can ack or redirect, rather
        # than re-poking every window until the max-nudge cap. One classifier-
        # driven nudge is still allowed first, to catch a queen that genuinely
        # stalled before it ever recorded tasks.
        if reason == ParkReason.TURN_DONE and not pctx.open_tasks and self._nudge_count >= 1:
            return ESCALATE_HEARTBEAT
        verdict = await self._classify_fn(pctx, llm)
        # A failed/absent classifier is not a real "continue" — never let a
        # transient LLM glitch manufacture a nudge at a parked queen. No-op and
        # try again next window.
        if verdict.errored:
            return None
        if verdict.needs_human:
            return ESCALATE_BLOCKER
        if verdict.is_done:
            return REPORT_DONE
        return REPORT_PROGRESS

    def _ui_attached(self, session_id: str) -> bool:
        fn = self._has_attached_ui or _manager_has_attached_ui
        try:
            return bool(fn(session_id))
        except Exception:
            logger.debug("sentinel: has_attached_ui failed", exc_info=True)
            return False

    def _report(
        self,
        colony_id: str,
        session_id: str,
        reason: ParkReason,
        pctx: ParkContext,
        cfg: store.NotificationsConfig,
        kind: str,
    ) -> None:
        """Tell the human. Progress is Inbox-feed-only; remote channels are
        suppressed while the user is at the desktop; identical consecutive
        reports collapse. Anything but progress holds the source until resume."""
        # Progress is the passive Inbox feed only — never an away channel.
        if kind == REPORT_PROGRESS and cfg.channel != notifier.CHANNEL_HIVE:
            return
        if cfg.channel != notifier.CHANNEL_HIVE and not store.escalate_when_ui_attached() and self._ui_attached(session_id):
            logger.info("[sentinel] report suppressed — UI attached (colony=%s)", colony_id)
            return
        summary = self._question_text(pctx)
        if (kind, summary) == self._last_report_sig:
            return  # collapse identical consecutive reports
        self._last_report_sig = (kind, summary)

        esc_id = f"esc_{uuid.uuid4().hex}"
        payload = {
            "escalation_id": esc_id,
            "colony_id": colony_id,
            "session_id": session_id,
            "correlation_token": token.make_token(esc_id),
            "park_reason": reason.value,
            "kind": kind,
            "question_text": summary,
            "channel": cfg.channel,
            "target": cfg.target,
            "thread": cfg.thread,
        }
        fn = self._on_escalate or _manager_enqueue_escalation
        try:
            accepted = bool(fn(payload))
        except Exception:
            logger.warning("sentinel: report enqueue raised", exc_info=True)
            return
        if not accepted:
            logger.warning("[sentinel] report not delivered (colony=%s kind=%s)", colony_id, kind)
            return
        # Progress re-evaluates next cycle; every other kind holds until resume.
        if kind != REPORT_PROGRESS:
            self._held = True
        logger.info("[sentinel] report %s (colony=%s esc=%s)", kind, colony_id, esc_id)

    # ----- message bodies -------------------------------------------------

    def _nudge_body(self, pctx: ParkContext) -> str:
        goal = f"Your goal: {pctx.goal}. " if pctx.goal else ""
        tasks = ", ".join(pctx.open_tasks[:5]) or "open work remains"
        workers = ""
        if pctx.running_workers:
            n = len(pctx.running_workers)
            workers = (
                f" NOTE: {n} worker{'' if n == 1 else 's'} from an earlier fan-out "
                f"{'is' if n == 1 else 'are'} still running:\n"
                f"{format_running_workers(pctx.running_workers)}\n"
                "Their results arrive as WORKER_REPORT messages — wait for those rather "
                "than re-dispatching the same tasks or summarizing the batch early."
            )
        return (
            f"{goal}You paused, but the goal is not finished — still to do: {tasks}. "
            "Continue now and keep working toward the goal autonomously. Do NOT pause to "
            "ask permission or for a progress check-in; only stop via ask_user if you "
            "genuinely cannot proceed without a human decision."
            f"{workers}"
        )

    def _question_text(self, pctx: ParkContext) -> str:
        if pctx.pending_questions:
            return "\n".join(f"- {q.get('prompt', q)}" for q in pctx.pending_questions[:5])
        return pctx.last_assistant_text.strip()[:1500] or "(the queen stalled with no message)"


# ----- default singleton hooks (overridable in tests) ---------------------


def _manager_enqueue_escalation(payload: dict[str, Any]) -> bool:
    from framework.sentinel.manager import get_sentinel_manager

    mgr = get_sentinel_manager()
    if mgr is None:
        return False
    return mgr.enqueue_escalation(payload)


def _manager_has_attached_ui(session_id: str) -> bool:
    from framework.sentinel.manager import get_sentinel_manager

    mgr = get_sentinel_manager()
    if mgr is None:
        return False
    return mgr.has_attached_ui(session_id)
