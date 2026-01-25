"""Tests for the Runtime class - the agent's interface to record decisions."""

import pytest
from pathlib import Path
import asyncio

from framework import Runtime
from framework.schemas.decision import DecisionType


@pytest.mark.asyncio
class TestRuntimeBasics:
    """Test basic runtime lifecycle."""

    async def test_start_and_end_run(self, tmp_path: Path):
        """Test starting and ending a run."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()

        run_id = await runtime.start_run(
            goal_id="test_goal",
            goal_description="Test goal description",
            input_data={"key": "value"},
        )

        assert run_id.startswith("run_")
        assert runtime.current_run is not None
        assert runtime.current_run.goal_id == "test_goal"

        await runtime.end_run(success=True, narrative="Test completed")

        assert runtime.current_run is None

    async def test_end_without_start_is_graceful(self, tmp_path: Path):
        """Ending a run that wasn't started logs warning but doesn't raise."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()

        # Should not raise, but log a warning instead
        await runtime.end_run(success=True)
        assert runtime.current_run is None

    async def test_run_saved_on_end(self, tmp_path: Path):
        """Run is saved to storage when ended."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()

        run_id = await runtime.start_run("test_goal", "Test")
        await runtime.end_run(success=True)

        # Check file exists
        run_file = tmp_path / "runs" / f"{run_id}.json"
        assert run_file.exists()


@pytest.mark.asyncio
class TestDecisionRecording:
    """Test recording decisions."""

    async def test_basic_decision(self, tmp_path: Path):
        """Test recording a basic decision."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        decision_id = await runtime.decide(
            intent="Choose a greeting",
            options=[
                {"id": "hello", "description": "Say hello"},
                {"id": "hi", "description": "Say hi"},
            ],
            chosen="hello",
            reasoning="More formal",
        )

        assert decision_id.startswith("dec_")
        assert len(runtime.current_run.decisions) == 1

        decision = runtime.current_run.decisions[0]
        assert decision.intent == "Choose a greeting"
        assert decision.chosen_option_id == "hello"
        assert len(decision.options) == 2

        await runtime.end_run(success=True)

    async def test_decision_without_run_is_graceful(self, tmp_path: Path):
        """Recording decisions without a run logs warning and returns empty string."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()

        # Should not raise, but log a warning and return empty string
        decision_id = await runtime.decide(
            intent="Test",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        assert decision_id == ""

    async def test_decision_with_node_context(self, tmp_path: Path):
        """Test decision with node ID context."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        # Set node context (sync)
        runtime.set_node("search-node")

        await runtime.decide(
            intent="Search query",
            options=[{"id": "web", "description": "Web search"}],
            chosen="web",
            reasoning="Need web results",
        )

        decision = runtime.current_run.decisions[0]
        assert decision.node_id == "search-node"

        await runtime.end_run(success=True)

    async def test_decision_type(self, tmp_path: Path):
        """Test different decision types."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        await runtime.decide(
            intent="Which tool to use",
            options=[
                {"id": "search", "description": "Use search API"},
                {"id": "cache", "description": "Use cached data"},
            ],
            chosen="search",
            reasoning="Need fresh data",
            decision_type=DecisionType.TOOL_SELECTION,
        )

        decision = runtime.current_run.decisions[0]
        assert decision.decision_type == DecisionType.TOOL_SELECTION

        await runtime.end_run(success=True)


@pytest.mark.asyncio
class TestOutcomeRecording:
    """Test recording outcomes of decisions."""

    async def test_record_successful_outcome(self, tmp_path: Path):
        """Test recording a successful outcome."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        decision_id = await runtime.decide(
            intent="Test action",
            options=[{"id": "a", "description": "Action A"}],
            chosen="a",
            reasoning="Test",
        )

        await runtime.record_outcome(
            decision_id=decision_id,
            success=True,
            result={"data": "success"},
            summary="Action completed successfully",
            tokens_used=100,
            latency_ms=50,
        )

        decision = runtime.current_run.decisions[0]
        assert decision.outcome is not None
        assert decision.outcome.success is True
        assert decision.outcome.result == {"data": "success"}
        assert decision.was_successful is True

        await runtime.end_run(success=True)

    async def test_record_failed_outcome(self, tmp_path: Path):
        """Test recording a failed outcome."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        decision_id = await runtime.decide(
            intent="Test action",
            options=[{"id": "a", "description": "Action A"}],
            chosen="a",
            reasoning="Test",
        )

        await runtime.record_outcome(
            decision_id=decision_id,
            success=False,
            error="API rate limited",
        )

        decision = runtime.current_run.decisions[0]
        assert decision.outcome is not None
        assert decision.outcome.success is False
        assert decision.outcome.error == "API rate limited"
        assert decision.was_successful is False

        await runtime.end_run(success=False)

    async def test_metrics_updated_on_outcome(self, tmp_path: Path):
        """Test that metrics are updated when outcomes are recorded."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        # Successful decision
        d1 = await runtime.decide(
            intent="Action 1",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        await runtime.record_outcome(d1, success=True, tokens_used=100)

        # Failed decision
        d2 = await runtime.decide(
            intent="Action 2",
            options=[{"id": "b", "description": "B"}],
            chosen="b",
            reasoning="Test",
        )
        await runtime.record_outcome(d2, success=False)

        metrics = runtime.current_run.metrics
        assert metrics.total_decisions == 2
        assert metrics.successful_decisions == 1
        assert metrics.failed_decisions == 1
        assert metrics.total_tokens == 100

        await runtime.end_run(success=False)


@pytest.mark.asyncio
class TestProblemReporting:
    """Test problem reporting."""

    async def test_report_problem(self, tmp_path: Path):
        """Test reporting a problem."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        problem_id = await runtime.report_problem(
            severity="critical",
            description="API is unavailable",
            root_cause="Service outage",
            suggested_fix="Implement fallback to cached data",
        )

        assert problem_id.startswith("prob_")
        assert len(runtime.current_run.problems) == 1

        problem = runtime.current_run.problems[0]
        assert problem.severity == "critical"
        assert problem.description == "API is unavailable"

        await runtime.end_run(success=False)

    async def test_problem_linked_to_decision(self, tmp_path: Path):
        """Test linking a problem to a decision."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        decision_id = await runtime.decide(
            intent="Call API",
            options=[{"id": "call", "description": "Make API call"}],
            chosen="call",
            reasoning="Need data",
        )

        await runtime.report_problem(
            severity="warning",
            description="API slow",
            decision_id=decision_id,
        )

        problem = runtime.current_run.problems[0]
        assert problem.decision_id == decision_id

        await runtime.end_run(success=True)


@pytest.mark.asyncio
class TestConvenienceMethods:
    """Test convenience methods."""

    async def test_quick_decision(self, tmp_path: Path):
        """Test quick_decision for simple cases."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        await runtime.quick_decision(
            intent="Log message",
            action="Write to stdout",
            reasoning="Standard logging",
        )

        decision = runtime.current_run.decisions[0]
        assert decision.intent == "Log message"
        assert len(decision.options) == 1
        assert decision.options[0].id == "action"

        await runtime.end_run(success=True)

    async def test_decide_and_execute_success(self, tmp_path: Path):
        """Test decide_and_execute with successful execution."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        async def do_action():
            return {"computed": 42}

        decision_id, result = await runtime.decide_and_execute(
            intent="Compute value",
            options=[{"id": "compute", "description": "Run computation"}],
            chosen="compute",
            reasoning="Need the value",
            executor=do_action,
        )

        assert result == {"computed": 42}
        decision = runtime.current_run.decisions[0]
        assert decision.was_successful is True
        assert decision.outcome.result == {"computed": 42}

        await runtime.end_run(success=True)

    async def test_decide_and_execute_failure(self, tmp_path: Path):
        """Test decide_and_execute with failed execution."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        async def do_failing_action():
            raise ValueError("Something went wrong")

        with pytest.raises(ValueError, match="Something went wrong"):
            await runtime.decide_and_execute(
                intent="Failing action",
                options=[{"id": "fail", "description": "Will fail"}],
                chosen="fail",
                reasoning="Test failure",
                executor=do_failing_action,
            )

        decision = runtime.current_run.decisions[0]
        assert decision.was_successful is False
        assert "Something went wrong" in decision.outcome.error

        await runtime.end_run(success=False)


@pytest.mark.asyncio
class TestNarrativeGeneration:
    """Test automatic narrative generation."""

    async def test_default_narrative_success(self, tmp_path: Path):
        """Test default narrative for successful run."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        d1 = await runtime.decide(
            intent="Action",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        await runtime.record_outcome(d1, success=True)

        await runtime.end_run(success=True)

        # Load and check narrative
        # Storage operations are now async on the storage backend directly
        runs = await runtime.storage.get_runs_by_goal("test_goal")
        run = await runtime.storage.load_run(runs[0])
        assert "completed successfully" in run.narrative

    async def test_default_narrative_failure(self, tmp_path: Path):
        """Test default narrative for failed run."""
        runtime = Runtime(tmp_path)
        await runtime.initialize()
        await runtime.start_run("test_goal", "Test")

        d1 = await runtime.decide(
            intent="Failing action",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        await runtime.record_outcome(d1, success=False, error="Test error")

        await runtime.report_problem(
            severity="critical",
            description="Test critical issue",
        )

        await runtime.end_run(success=False)

        runs = await runtime.storage.get_runs_by_goal("test_goal")
        run = await runtime.storage.load_run(runs[0])
        assert "failed" in run.narrative
        assert "critical" in run.narrative.lower() or "Critical" in run.narrative
