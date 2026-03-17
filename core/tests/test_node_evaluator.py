"""Tests for NodeEvaluator protocol and executor integration."""

from __future__ import annotations

from typing import Any

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.evaluator import NodeEvaluator
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult, NodeSpec
from framework.schemas.eval_report import EvalReport


# ---- Dummy runtime (no real logging) ----
class DummyRuntime:
    execution_id = ""

    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass


# ---- Fake node that always succeeds ----
class SuccessNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"result": "hello"},
            tokens_used=50,
            latency_ms=100,
        )


# ---- Fake node that always fails ----
class FailingNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(success=False, error="intentional failure")


# ---- Concrete NodeEvaluator for testing ----
class MockEvaluator:
    """Satisfies the NodeEvaluator protocol."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def evaluate(
        self,
        node_spec: NodeSpec,
        node_result: NodeResult,
        memory: dict[str, Any],
    ) -> EvalReport:
        self.calls.append(
            {
                "node_id": node_spec.id,
                "output": node_result.output,
                "memory_keys": list(memory.keys()),
            }
        )
        return EvalReport(
            node_id=node_spec.id,
            faithfulness=0.9,
            relevance=0.8,
            completeness=0.7,
            cost_efficiency=0.95,
            weak_dimensions=["completeness"],
            tokens_used=node_result.tokens_used,
        )


class FailingEvaluator:
    """Evaluator that raises to test non-blocking error handling."""

    async def evaluate(
        self,
        node_spec: NodeSpec,
        node_result: NodeResult,
        memory: dict[str, Any],
    ) -> EvalReport:
        raise RuntimeError("Evaluator crashed")


# ---- Helper to build a simple one-node graph ----
def _one_node_graph(node_id: str = "n1") -> GraphSpec:
    return GraphSpec(
        id="graph-1",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id=node_id,
                name="test-node",
                description="a test node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node=node_id,
        terminal_nodes=[node_id],
    )


def _goal() -> Goal:
    return Goal(id="g1", name="test-goal", description="test")


# ---- Schema tests ----


class TestEvalReport:
    def test_defaults(self):
        report = EvalReport(node_id="n1")
        assert report.faithfulness == 1.0
        assert report.relevance == 1.0
        assert report.completeness == 1.0
        assert report.cost_efficiency == 1.0
        assert report.weak_dimensions == []
        assert report.tokens_used == 0
        assert report.evaluator_model is None

    def test_custom_scores(self):
        report = EvalReport(
            node_id="n1",
            faithfulness=0.5,
            relevance=0.3,
            weak_dimensions=["faithfulness", "relevance"],
            evaluator_model="gpt-4o",
        )
        assert report.faithfulness == 0.5
        assert report.relevance == 0.3
        assert report.weak_dimensions == ["faithfulness", "relevance"]
        assert report.evaluator_model == "gpt-4o"

    def test_score_bounds(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            EvalReport(node_id="n1", faithfulness=1.5)
        with pytest.raises(ValidationError):
            EvalReport(node_id="n1", relevance=-0.1)

    def test_extra_fields_allowed(self):
        report = EvalReport(node_id="n1", custom_metric=0.42)
        assert report.model_dump()["custom_metric"] == 0.42


# ---- Protocol tests ----


class TestNodeEvaluatorProtocol:
    def test_mock_evaluator_satisfies_protocol(self):
        evaluator = MockEvaluator()
        assert isinstance(evaluator, NodeEvaluator)

    def test_failing_evaluator_satisfies_protocol(self):
        evaluator = FailingEvaluator()
        assert isinstance(evaluator, NodeEvaluator)


# ---- Executor integration tests ----


class TestExecutorEvaluatorHook:
    @pytest.mark.asyncio
    async def test_evaluator_called_on_success(self):
        evaluator = MockEvaluator()
        executor = GraphExecutor(
            runtime=DummyRuntime(),
            node_registry={"n1": SuccessNode()},
            node_evaluator=evaluator,
        )
        result = await executor.execute(graph=_one_node_graph(), goal=_goal())

        assert result.success is True
        assert len(evaluator.calls) == 1
        assert evaluator.calls[0]["node_id"] == "n1"
        assert evaluator.calls[0]["output"] == {"result": "hello"}

    @pytest.mark.asyncio
    async def test_evaluator_not_called_on_failure(self):
        evaluator = MockEvaluator()
        executor = GraphExecutor(
            runtime=DummyRuntime(),
            node_registry={"n1": FailingNode()},
            node_evaluator=evaluator,
        )
        result = await executor.execute(graph=_one_node_graph(), goal=_goal())

        assert result.success is False
        assert len(evaluator.calls) == 0

    @pytest.mark.asyncio
    async def test_evaluator_failure_is_non_blocking(self):
        executor = GraphExecutor(
            runtime=DummyRuntime(),
            node_registry={"n1": SuccessNode()},
            node_evaluator=FailingEvaluator(),
        )
        result = await executor.execute(graph=_one_node_graph(), goal=_goal())

        # Execution should succeed even though evaluator crashed
        assert result.success is True
        assert result.path == ["n1"]

    @pytest.mark.asyncio
    async def test_no_evaluator_is_default(self):
        executor = GraphExecutor(
            runtime=DummyRuntime(),
            node_registry={"n1": SuccessNode()},
        )
        # No evaluator set — should work exactly as before
        result = await executor.execute(graph=_one_node_graph(), goal=_goal())
        assert result.success is True
