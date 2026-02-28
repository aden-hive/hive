"""
Tests for run_id propagation across StreamRuntime and OutcomeAggregator.

Ensures:
1. StreamRuntime creates a run with a stable run_id
2. Decisions propagate run_id into OutcomeAggregator
3. Outcomes propagate run_id into OutcomeAggregator
4. Aggregated records can be traced back to run_id
"""

import pytest

from framework.runtime.stream_runtime import StreamRuntime
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.schemas.decision import DecisionType
from framework.graph.goal import Goal, SuccessCriterion
from framework.storage.concurrent import ConcurrentStorage


@pytest.fixture
def sample_goal():
    return Goal(
        id="goal-1",
        name="Test Goal",
        description="Validate run_id propagation",
        success_criteria=[
            SuccessCriterion(
                id="sc-1",
                description="Decision succeeds",
                metric="custom",
                target="100%",
            )
        ],
    )


@pytest.fixture
def storage(tmp_path):
    return ConcurrentStorage(tmp_path)


@pytest.fixture
def aggregator(sample_goal):
    return OutcomeAggregator(goal=sample_goal)


def test_run_id_propagation_to_outcome_aggregator(storage, aggregator):
    """
    Validate that run_id created in StreamRuntime is propagated
    into OutcomeAggregator for both decisions and outcomes.
    """

    runtime = StreamRuntime(
        stream_id="test-stream",
        storage=storage,
        outcome_aggregator=aggregator,
    )

    execution_id = "exec-123"

    # --- Start run ---
    run_id = runtime.start_run(
        execution_id=execution_id,
        goal_id="goal-1",
        goal_description="Run ID propagation test",
    )

    assert run_id is not None

    # --- Record decision ---
    decision_id = runtime.decide(
        execution_id=execution_id,
        intent="Test decision",
        options=[{"id": "opt-1", "description": "Only option"}],
        chosen="opt-1",
        reasoning="Single-path decision",
        decision_type=DecisionType.CUSTOM,
    )

    assert decision_id != ""

    # --- Record outcome ---
    runtime.record_outcome(
        execution_id=execution_id,
        decision_id=decision_id,
        success=True,
        result={"ok": True},
        summary="Decision succeeded",
    )

    # --- Validate aggregator state ---
    assert len(aggregator._decisions) == 1

    record = aggregator._decisions[0]

    assert record.stream_id == "test-stream"
    assert record.execution_id == execution_id
    assert record.decision.id == decision_id
    assert record.outcome is not None
    assert record.outcome.success is True

    assert record.run_id == run_id
