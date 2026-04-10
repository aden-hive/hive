"""Tests for SubagentJudge — the only alive piece of the legacy subagent surface.

The old EventLoopNode.delegate_to_sub_agent / report_to_parent / mark_complete
mechanism is gone. Subagent execution as a per-context concept no longer
exists in the new architecture; what survives is :class:`SubagentJudge`,
a JudgeProtocol implementation that terminates a bounded loop when its
output keys are filled.

The judge is consumed by injecting it into ``AgentLoop(judge=...)`` —
test_event_loop_node.py exercises the integration. This file unit-tests
the judge in isolation.
"""

from __future__ import annotations

import pytest

from framework.agent_loop.agent_loop import SubagentJudge
from framework.agent_loop.internals.types import JudgeVerdict


class TestSubagentJudge:
    """Unit tests for the SubagentJudge class."""

    @pytest.mark.asyncio
    async def test_accepts_when_output_keys_filled(self):
        """ACCEPT when missing_keys is empty, even if a tool just ran."""
        judge = SubagentJudge(task="Check profile at https://example.com/user123")

        verdict = await judge.evaluate(
            {
                "missing_keys": [],
                "tool_results": [{"tool_name": "browser_navigate", "content": "ok"}],
                "iteration": 1,
            }
        )

        assert verdict.action == "ACCEPT"
        assert verdict.feedback == ""

    @pytest.mark.asyncio
    async def test_retries_with_task_and_missing_keys_in_feedback(self):
        """RETRY when output keys are missing, with task + keys + nudge in feedback."""
        task = "Scrape profile at https://example.com/user456"
        judge = SubagentJudge(task=task)

        verdict = await judge.evaluate(
            {
                "missing_keys": ["findings", "summary"],
                "tool_results": [],
                "iteration": 1,
            }
        )

        assert verdict.action == "RETRY"
        assert task in verdict.feedback
        assert "findings" in verdict.feedback
        assert "summary" in verdict.feedback
        assert "set_output" in verdict.feedback

    @pytest.mark.asyncio
    async def test_returns_judge_verdict_instance(self):
        """The judge returns a JudgeVerdict, not a plain dict."""
        judge = SubagentJudge(task="task")

        accept = await judge.evaluate(
            {"missing_keys": [], "tool_results": [], "iteration": 0}
        )
        retry = await judge.evaluate(
            {"missing_keys": ["x"], "tool_results": [], "iteration": 0}
        )

        assert isinstance(accept, JudgeVerdict)
        assert isinstance(retry, JudgeVerdict)

    @pytest.mark.asyncio
    async def test_constructible_with_max_iterations(self):
        """SubagentJudge accepts an optional max_iterations parameter."""
        judge = SubagentJudge(task="t", max_iterations=10)
        assert judge is not None
        # The constructor must not crash; the judge still functions normally.
        verdict = await judge.evaluate({"missing_keys": [], "tool_results": [], "iteration": 0})
        assert verdict.action == "ACCEPT"
