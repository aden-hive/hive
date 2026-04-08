"""Judge evaluation pipeline for the event loop."""

from __future__ import annotations

import logging
from collections.abc import Callable

from framework.agent_loop.conversation import NodeConversation
from framework.agent_loop.internals.types import JudgeProtocol, JudgeVerdict, OutputAccumulator
from framework.orchestrator.node import NodeContext

logger = logging.getLogger(__name__)


class SubagentJudge:
    """Judge for subagent execution."""

    def __init__(self, task: str, max_iterations: int = 10):
        self._task = task
        self._max_iterations = max_iterations

    async def evaluate(self, context: dict[str, object]) -> JudgeVerdict:
        missing = context.get("missing_keys", [])
        if not isinstance(missing, list) or not missing:
            return JudgeVerdict(action="ACCEPT", feedback="")

        iteration = context.get("iteration", 0)
        if not isinstance(iteration, int):
            iteration = 0
        remaining = self._max_iterations - iteration - 1

        if remaining <= 3:
            urgency = (
                f"URGENT: Only {remaining} iterations left. "
                f"Stop all other work and call set_output NOW for: {missing}"
            )
        elif remaining <= self._max_iterations // 2:
            urgency = (
                f"WARNING: {remaining} iterations remaining. "
                f"You must call set_output for: {missing}"
            )
        else:
            urgency = f"Missing output keys: {missing}. Use set_output to provide them."

        return JudgeVerdict(action="RETRY", feedback=f"Your task: {self._task}\n{urgency}")


async def judge_turn(
    *,
    mark_complete_flag: bool,
    judge: JudgeProtocol | None,
    ctx: NodeContext,
    conversation: NodeConversation,
    accumulator: OutputAccumulator,
    assistant_text: str,
    tool_results: list[dict[str, object]],
    iteration: int,
    get_missing_output_keys_fn: Callable[
        [OutputAccumulator, list[str] | None, list[str] | None],
        list[str],
    ],
    max_context_tokens: int,
) -> JudgeVerdict:
    """Evaluate the current state using judge or implicit logic.

    Evaluation levels (in order):
      0. Short-circuits: mark_complete, skip_judge, tool-continue.
      1. Custom judge (JudgeProtocol) — full authority when set.
      2. Implicit judge — output-key check + optional conversation-aware
         quality gate (when ``success_criteria`` is defined).

    Returns a JudgeVerdict.  ``feedback=None`` means no real evaluation
    happened (skip_judge, tool-continue); the caller must not inject a
    feedback message.  Any non-None feedback (including ``""``) means a
    real evaluation occurred and will be logged into the conversation.
    """
    # --- Level 0: short-circuits (no evaluation) -----------------------

    if mark_complete_flag:
        return JudgeVerdict(action="ACCEPT")

    if ctx.node_spec.skip_judge:
        return JudgeVerdict(action="RETRY")  # feedback=None → not logged

    # --- Level 1: custom judge -----------------------------------------

    if judge is not None:
        context = {
            "assistant_text": assistant_text,
            "tool_calls": tool_results,
            "output_accumulator": accumulator.to_dict(),
            "accumulator": accumulator,
            "iteration": iteration,
            "conversation_summary": conversation.export_summary(),
            "output_keys": ctx.node_spec.output_keys,
            "missing_keys": get_missing_output_keys_fn(
                accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
            ),
        }
        verdict = await judge.evaluate(context)
        # Ensure evaluated RETRY always carries feedback for logging.
        if verdict.action == "RETRY" and not verdict.feedback:
            return JudgeVerdict(action="RETRY", feedback="Custom judge returned RETRY.")
        return verdict

    # --- Level 2: implicit judge ---------------------------------------

    # Real tool calls were made — let the agent keep working.
    if tool_results:
        return JudgeVerdict(action="RETRY")  # feedback=None → not logged

    missing = get_missing_output_keys_fn(
        accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
    )

    if missing:
        return JudgeVerdict(
            action="RETRY",
            feedback=(
                f"Task incomplete. Required outputs not yet produced: {missing}. "
                f"Follow your system prompt instructions to complete the work."
            ),
        )

    # All output keys present — run safety checks before accepting.

    output_keys = ctx.node_spec.output_keys or []
    nullable_keys = set(ctx.node_spec.nullable_output_keys or [])

    # All-nullable with nothing set → node produced nothing useful.
    all_nullable = output_keys and nullable_keys >= set(output_keys)
    none_set = not any(accumulator.get(k) is not None for k in output_keys)
    if all_nullable and none_set:
        return JudgeVerdict(
            action="RETRY",
            feedback=(
                f"No output keys have been set yet. "
                f"Use set_output to set at least one of: {output_keys}"
            ),
        )

    # Queen with no output keys → continuous interaction node.
    # Inject tool-use pressure instead of auto-accepting.
    if not output_keys and ctx.supports_direct_user_io:
        return JudgeVerdict(
            action="RETRY",
            feedback=(
                "STOP describing what you will do. "
                "You have FULL access to all tools — file creation, "
                "shell commands, MCP tools — and you CAN call them "
                "directly in your response. Respond ONLY with tool "
                "calls, no prose. Execute the task now."
            ),
        )

    # Level 2b: conversation-aware quality check (if success_criteria set)
    if ctx.node_spec.success_criteria and ctx.llm:
        from framework.orchestrator.conversation_judge import evaluate_phase_completion

        verdict = await evaluate_phase_completion(
            llm=ctx.llm,
            conversation=conversation,
            phase_name=ctx.node_spec.name,
            phase_description=ctx.node_spec.description,
            success_criteria=ctx.node_spec.success_criteria,
            accumulator_state=accumulator.to_dict(),
            max_context_tokens=max_context_tokens,
        )
        if verdict.action != "ACCEPT":
            return JudgeVerdict(
                action=verdict.action,
                feedback=verdict.feedback or "Phase criteria not met.",
            )

    return JudgeVerdict(action="ACCEPT", feedback="")
