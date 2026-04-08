"""Tests for OutcomeAggregator.evaluate_criterion() — all four metric types.

Covers the dispatch table in OutcomeAggregator.evaluate_criterion:
  - output_contains
  - output_equals
  - custom        (safe_eval expression)
  - llm_judge     (delegates to framework.graph.judge.judge_criterion)

Plus the unknown-metric fallback.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from framework.graph.goal import Goal, SuccessCriterion
from framework.runtime.outcome_aggregator import OutcomeAggregator


def _goal(criterion: SuccessCriterion) -> Goal:
    return Goal(
        id="g1",
        name="Test Goal",
        description="test",
        success_criteria=[criterion],
        constraints=[],
    )


def _agg(criterion: SuccessCriterion, llm_provider=None) -> OutcomeAggregator:
    return OutcomeAggregator(_goal(criterion), llm_provider=llm_provider)


# ----------------------------------------------------------------------
# output_contains
# ----------------------------------------------------------------------


class TestOutputContains:
    @pytest.mark.asyncio
    async def test_substring_present_returns_true(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="must mention widgets",
            metric="output_contains",
            target="widgets",
        )
        assert await _agg(c).evaluate_criterion(c, "we sell widgets here") is True

    @pytest.mark.asyncio
    async def test_substring_absent_returns_false(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="must mention widgets",
            metric="output_contains",
            target="widgets",
        )
        assert await _agg(c).evaluate_criterion(c, "nothing relevant") is False

    @pytest.mark.asyncio
    async def test_non_string_output_is_stringified(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="contains 42",
            metric="output_contains",
            target="42",
        )
        assert await _agg(c).evaluate_criterion(c, {"answer": 42}) is True


# ----------------------------------------------------------------------
# output_equals
# ----------------------------------------------------------------------


class TestOutputEquals:
    @pytest.mark.asyncio
    async def test_exact_match(self) -> None:
        c = SuccessCriterion(
            id="c1", description="exact", metric="output_equals", target=42
        )
        assert await _agg(c).evaluate_criterion(c, 42) is True

    @pytest.mark.asyncio
    async def test_string_strip_match(self) -> None:
        c = SuccessCriterion(
            id="c1", description="exact", metric="output_equals", target="result"
        )
        assert await _agg(c).evaluate_criterion(c, "  result  ") is True

    @pytest.mark.asyncio
    async def test_mismatch_returns_false(self) -> None:
        c = SuccessCriterion(
            id="c1", description="exact", metric="output_equals", target="expected"
        )
        assert await _agg(c).evaluate_criterion(c, "actual") is False


# ----------------------------------------------------------------------
# custom (safe_eval)
# ----------------------------------------------------------------------


class TestCustomMetric:
    @pytest.mark.asyncio
    async def test_length_expression_met(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="long enough",
            metric="custom",
            target="len(output) >= 5",
        )
        assert await _agg(c).evaluate_criterion(c, "long enough") is True

    @pytest.mark.asyncio
    async def test_length_expression_not_met(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="long enough",
            metric="custom",
            target="len(output) >= 5",
        )
        assert await _agg(c).evaluate_criterion(c, "hi") is False

    @pytest.mark.asyncio
    async def test_dict_field_access(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="status ok",
            metric="custom",
            target="output.get('status') == 'ok'",
        )
        agg = _agg(c)
        assert await agg.evaluate_criterion(c, {"status": "ok"}) is True
        assert await agg.evaluate_criterion(c, {"status": "error"}) is False

    @pytest.mark.asyncio
    async def test_invalid_expression_returns_false(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="bad expr",
            metric="custom",
            target="this is not valid python",
        )
        assert await _agg(c).evaluate_criterion(c, "anything") is False


# ----------------------------------------------------------------------
# llm_judge
# ----------------------------------------------------------------------


def _mock_llm(response_content: str) -> SimpleNamespace:
    return SimpleNamespace(
        acomplete=AsyncMock(return_value=SimpleNamespace(content=response_content))
    )


class TestLLMJudge:
    @pytest.mark.asyncio
    async def test_no_provider_returns_false(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="semantically correct",
            metric="llm_judge",
            target="answer is accurate",
        )
        assert await _agg(c).evaluate_criterion(c, "anything") is False

    @pytest.mark.asyncio
    async def test_judge_says_met(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="semantically correct",
            metric="llm_judge",
            target="answer is accurate",
        )
        llm = _mock_llm('{"met": true, "confidence": 0.9, "reason": "ok"}')
        assert await _agg(c, llm_provider=llm).evaluate_criterion(c, "blue") is True
        llm.acomplete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_judge_says_not_met(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="semantically correct",
            metric="llm_judge",
            target="answer is accurate",
        )
        llm = _mock_llm('{"met": false, "confidence": 0.8, "reason": "wrong"}')
        assert await _agg(c, llm_provider=llm).evaluate_criterion(c, "green") is False

    @pytest.mark.asyncio
    async def test_judge_handles_fenced_json(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="semantically correct",
            metric="llm_judge",
            target="answer is accurate",
        )
        llm = _mock_llm('```json\n{"met": true, "confidence": 1.0}\n```')
        assert await _agg(c, llm_provider=llm).evaluate_criterion(c, "x") is True

    @pytest.mark.asyncio
    async def test_judge_llm_failure_returns_false(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="semantically correct",
            metric="llm_judge",
            target="answer is accurate",
        )
        llm = SimpleNamespace(acomplete=AsyncMock(side_effect=RuntimeError("boom")))
        assert await _agg(c, llm_provider=llm).evaluate_criterion(c, "x") is False


# ----------------------------------------------------------------------
# Unknown metric
# ----------------------------------------------------------------------


class TestUnknownMetric:
    @pytest.mark.asyncio
    async def test_unknown_metric_returns_false(self) -> None:
        c = SuccessCriterion(
            id="c1",
            description="mystery",
            metric="not_a_real_metric",
            target="whatever",
        )
        assert await _agg(c).evaluate_criterion(c, "output") is False
