"""Nudge-vs-escalate classifier for a parked colony queen.

The colony queen often pauses *before its goal is done* — a progress
paragraph ending in "shall we continue?", or an ``ask_user`` that asks the
same. When the goal still has open work, most of these are spurious
permission-seeking the harness should push through (``continue``). A few are
genuine blockers a human must resolve (``needs_human``): an expired login, a
crashed browser, an ambiguous requirement the agent cannot decide.

``ParkReason`` alone can't tell these apart (both arrive as ``TURN_DONE`` /
``ASK_USER``), so we ask a cheap one-shot LLM, grounded in the goal, the open
tasks, the queen's last message, any pending questions, and recent tool
errors. Hard blockers (broken park reasons, detected auth/crash errors) are
decided *before* this is ever called — the classifier only sees the
ambiguous middle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from framework.config import get_aux_max_tokens

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

VERDICT_CONTINUE = "continue"
VERDICT_NEEDS_HUMAN = "needs_human"
VERDICT_DONE = "done"


@dataclass
class ParkContext:
    """Everything the classifier (and the escalate message) needs."""

    park_reason: str
    goal: str | None = None
    open_tasks: list[str] = field(default_factory=list)
    last_assistant_text: str = ""
    # The user's most recent message (steer/instruction). The single most
    # authoritative signal of intent — e.g. an explicit "stop / wait for me"
    # must override the queen's standing authority to continue. Empty when the
    # last turn was the queen's.
    recent_user_text: str = ""
    pending_questions: list[dict] | None = None
    recent_errors: list[str] = field(default_factory=list)
    # Live worker snapshot at park time (each {worker_id, status, task}). A
    # queen idling while its fan-out is still running isn't stalled — it's
    # waiting; both the classifier and the nudge need this to avoid a false
    # "you stalled, go do work" push that invites duplicate dispatch.
    running_workers: list[dict] = field(default_factory=list)
    # Precomputed deterministic signal: a broken park or a detected
    # auth/crash error. When True the source escalates without calling the
    # classifier at all.
    hard_blocker: bool = False


def _fmt_elapsed(seconds: float) -> str:
    """Compact human-readable duration: ``45s``, ``12m``, ``2h3m``."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m}m" if m else f"{h}h"


def format_running_workers(workers: list[dict], limit: int = 8) -> str:
    """Render running workers as ``- <id> [<status>, <elapsed>]: <task>`` lines.

    Empty string when there are none. Shared by the classifier prompt and
    the sentinel nudge body so both describe the in-flight fan-out the same
    way. Elapsed time is omitted when not provided.
    """
    if not workers:
        return ""
    lines: list[str] = []
    for w in workers[:limit]:
        wid = str(w.get("worker_id", "?"))
        status = str(w.get("status", "?"))
        elapsed = w.get("elapsed_seconds")
        head = f"{status}, {_fmt_elapsed(elapsed)}" if isinstance(elapsed, (int, float)) and elapsed > 0 else status
        task = str(w.get("task", "")).strip()
        lines.append(f"- {wid} [{head}]: {task}" if task else f"- {wid} [{head}]")
    if len(workers) > limit:
        lines.append(f"- ... and {len(workers) - limit} more")
    return "\n".join(lines)


@dataclass
class ClassifierVerdict:
    verdict: str  # VERDICT_CONTINUE | VERDICT_NEEDS_HUMAN | VERDICT_DONE
    reason: str = ""
    # True when the verdict is NOT a real judgment but the conservative
    # fallback after a classifier failure (LLM raised) or with no LLM at all.
    # The verdict still defaults to ``continue`` so non-nudging callers stay
    # safe, but a caller that would *act* on continue (e.g. emit a nudge) can
    # check this and skip rather than poke a parked queen on a transient glitch.
    errored: bool = False

    @property
    def needs_human(self) -> bool:
        return self.verdict == VERDICT_NEEDS_HUMAN

    @property
    def is_done(self) -> bool:
        return self.verdict == VERDICT_DONE


_SYSTEM = (
    "You are the supervisor of an autonomous agent (the 'queen') that is working "
    "toward a goal with a task list. The queen has paused. Decide whether it should "
    "keep going on its own, or whether a human is genuinely needed.\n\n"
    "Answer 'continue' when the pause is just the queen seeking permission or "
    "reporting progress while work clearly remains (e.g. 'shall I continue?', "
    "'should I proceed to the next batch?'). The queen has standing authority to "
    "finish its goal without asking.\n"
    "Answer 'needs_human' ONLY for a genuine blocker the queen cannot resolve alone: "
    "expired/invalid login or credentials, a crashed or unavailable tool/browser, "
    "missing information only the human has, or a real decision with materially "
    "different outcomes. When unsure and work can still proceed, prefer 'continue'.\n"
    "Answer 'done' when the queen has clearly COMPLETED its goal — all work finished "
    "and a final result or summary delivered, with nothing left to do (e.g. a closing "
    "report, a final scoreboard, 'all done'). Judge completion from the goal, the "
    "absence of remaining work, and the queen's last message — never from an empty "
    "task list alone (a queen can stall before it ever records tasks).\n"
    "BLOCKED-REMAINDER — when the goal is substantially complete but a remainder is "
    "blocked by something the queen cannot resolve on its own (an external limit it has "
    "hit — rate/credit/quota/InMail/monthly limit — billing, exhausted capacity, or a "
    "dependency outside its control), do NOT answer 'continue': continuing is futile "
    "because the work cannot make progress. Answer 'done' if the queen has delivered a "
    "completion/closing report on what it finished, or 'needs_human' if the human must "
    "act on the blocker. 'continue' is ONLY for work that can actually progress now.\n"
    "EXCEPTION — user intent overrides standing authority: if the user's most recent "
    "message asked the queen to stop, pause, hold, wait for them, or hand control back, "
    "answer 'needs_human' even if work remains. (A message that merely redirects the "
    "work — 'stop using X, do Y instead' — is NOT a request to halt; keep going.)\n"
    "If workers from an earlier fan-out are still running, an idle queen is normally just "
    "waiting for their reports — that is healthy autonomous progress, not a blocker: "
    "answer 'continue'.\n\n"
    'Respond ONLY with JSON: {"verdict": "continue" | "needs_human" | "done", "reason": "<one short sentence>"}'
)


def _build_prompt(ctx: ParkContext) -> str:
    tasks = "\n".join(f"- {t}" for t in ctx.open_tasks[:10]) or "(none recorded)"
    questions = ""
    if ctx.pending_questions:
        qs = "; ".join(str(q.get("prompt", q)) for q in ctx.pending_questions[:5])
        questions = f"\nExplicit question(s) the queen asked: {qs}"
    errors = ""
    if ctx.recent_errors:
        errors = "\nRecent tool errors:\n" + "\n".join(f"- {e}" for e in ctx.recent_errors[:5])
    workers = ""
    if ctx.running_workers:
        workers = f"\nWorkers still running ({len(ctx.running_workers)}):\n" + format_running_workers(ctx.running_workers)
    user_msg = ""
    if ctx.recent_user_text.strip():
        user_msg = f'\nUser\'s most recent message:\n"""\n{ctx.recent_user_text[:1500]}\n"""'
    return (
        f"Goal: {ctx.goal or '(no goal recorded)'}\n"
        f"Open tasks still to do:\n{tasks}\n"
        f"Park reason: {ctx.park_reason}\n"
        f'Queen\'s last message:\n"""\n{ctx.last_assistant_text[:1500]}\n"""'
        f"{user_msg}{questions}{errors}{workers}\n\n"
        "Should the queen continue on its own, or does it need a human?"
    )


def _log_decision(ctx: ParkContext, verdict: ClassifierVerdict) -> None:
    """Emit the full classifier input + verdict as one structured INFO line.

    THIS IS THE CANONICAL RECORD of what Sentinel's classifier saw and how it
    decided — the hook for debugging spurious nudges/escalations (e.g. a queen
    nudged onward after it already reported its goal done). Every call to
    :func:`classify_park` logs exactly one ``classify_decision`` line, including
    the no-LLM and error fallbacks, so a missing line means the classifier was
    never reached (gated earlier in EscalationSource.render).

    Visibility: set ``HIVE_SENTINEL_LOG=1`` to divert the whole
    ``framework.sentinel.*`` namespace to ``<HIVE_HOME>/logs/sentinel.log``
    (see ``sentinel/manager.py:_install_sentinel_log_file``). Inspect with
    ``scripts/sentinel_classify_debug.py`` (pretty-prints/follows these lines),
    or raw::

        grep classify_decision ~/Library/Application\\ Support/Hive/**/logs/sentinel.log

    The payload is JSON so the debug script can parse it; the message tag
    ``classify_decision`` is the stable grep anchor — do not rename without
    updating the script.
    """
    try:
        payload = {
            "verdict": verdict.verdict,
            "reason": verdict.reason,
            "park_reason": ctx.park_reason,
            "goal": ctx.goal,
            "open_tasks": ctx.open_tasks,
            "last_assistant_text": ctx.last_assistant_text[:1500],
            "recent_user_text": ctx.recent_user_text[:500],
            "pending_questions": ctx.pending_questions,
            "recent_errors": ctx.recent_errors[:5],
            "running_workers": len(ctx.running_workers),
            "hard_blocker": ctx.hard_blocker,
        }
        logger.info("[sentinel] classify_decision %s", json.dumps(payload, ensure_ascii=False))
    except Exception:
        logger.debug("sentinel: classify_decision log failed", exc_info=True)


async def classify_park(ctx: ParkContext, llm: LLMProvider | None) -> ClassifierVerdict:
    """Classify an ambiguous park. On any failure, default to ``continue``.

    The conservative default is *continue* (keep the colony moving, don't
    raise a false alarm): genuine blockers almost always surface a hard
    signal handled deterministically before this is reached, so a classifier
    glitch should not strand a colony with a spurious escalation.

    Every return path emits one ``classify_decision`` log line via
    :func:`_log_decision` — the canonical record for debugging nudge/escalate
    behaviour. See that function for how to view it.
    """
    if llm is None:
        result = ClassifierVerdict(VERDICT_CONTINUE, "no llm available", errored=True)
        _log_decision(ctx, result)
        return result
    try:
        resp = await llm.acomplete(
            messages=[{"role": "user", "content": _build_prompt(ctx)}],
            system=_SYSTEM,
            max_tokens=get_aux_max_tokens(),
            json_mode=True,
        )
        data = json.loads((resp.content or "").strip())
        verdict = str(data.get("verdict", "")).lower().strip()
        reason = str(data.get("reason", ""))
        if verdict == VERDICT_NEEDS_HUMAN:
            result = ClassifierVerdict(VERDICT_NEEDS_HUMAN, reason)
        elif verdict == VERDICT_DONE:
            result = ClassifierVerdict(VERDICT_DONE, reason)
        else:
            result = ClassifierVerdict(VERDICT_CONTINUE, reason)
        _log_decision(ctx, result)
        return result
    except Exception:
        logger.debug("sentinel: classifier failed; defaulting to continue", exc_info=True)
        result = ClassifierVerdict(VERDICT_CONTINUE, "classifier error", errored=True)
        _log_decision(ctx, result)
        return result
