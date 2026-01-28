"""Tests for the Runtime class - the agent's interface to record decisions."""

from pathlib import Path

import pytest

from framework import Runtime
from framework.schemas.decision import DecisionType


class TestRuntimeBasics:
    """Test basic runtime lifecycle."""

    def test_start_and_end_run(self, tmp_path: Path):
        """Test starting and ending a run."""
        runtime = Runtime(tmp_path)

        run_id = runtime.start_run(
            goal_id="test_goal",
            goal_description="Test goal description",
            input_data={"key": "value"},
        )

        assert run_id.startswith("run_")
        assert runtime.current_run is not None
        assert runtime.current_run.goal_id == "test_goal"

        runtime.end_run(success=True, narrative="Test completed")

        assert runtime.current_run is None

    def test_end_without_start_is_graceful(self, tmp_path: Path):
        """Ending a run that wasn't started logs warning but doesn't raise."""
        runtime = Runtime(tmp_path)

        # Should not raise, but log a warning instead
        runtime.end_run(success=True)
        assert runtime.current_run is None

    def test_run_saved_on_end(self, tmp_path: Path):
        """Run is saved to storage when ended."""
        runtime = Runtime(tmp_path)

        run_id = runtime.start_run("test_goal", "Test")
        runtime.end_run(success=True)

        # Check file exists
        run_file = tmp_path / "runs" / f"{run_id}.json"
        assert run_file.exists()


class TestDecisionRecording:
    """Test recording decisions."""

    def test_basic_decision(self, tmp_path: Path):
        """Test recording a basic decision."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        decision_id = runtime.decide(
            intent="Choose a greeting",
            options=[
                {"id": "hello", "description": "Say hello"},
                {"id": "hi", "description": "Say hi"},
            ],
            chosen="hello",
            reasoning="More formal",
        )

        assert decision_id == "dec_0"
        assert len(runtime.current_run.decisions) == 1

        decision = runtime.current_run.decisions[0]
        assert decision.intent == "Choose a greeting"
        assert decision.chosen_option_id == "hello"
        assert len(decision.options) == 2

        runtime.end_run(success=True)

    def test_decision_without_run_is_graceful(self, tmp_path: Path):
        """Recording decisions without a run logs warning and returns empty string."""
        runtime = Runtime(tmp_path)

        # Should not raise, but log a warning and return empty string
        decision_id = runtime.decide(
            intent="Test",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        assert decision_id == ""

    def test_decision_with_node_context(self, tmp_path: Path):
        """Test decision with node ID context."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        # Set node context
        runtime.set_node("search-node")

        runtime.decide(
            intent="Search query",
            options=[{"id": "web", "description": "Web search"}],
            chosen="web",
            reasoning="Need web results",
        )

        decision = runtime.current_run.decisions[0]
        assert decision.node_id == "search-node"

        runtime.end_run(success=True)

    def test_decision_type(self, tmp_path: Path):
        """Test different decision types."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        runtime.decide(
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

        runtime.end_run(success=True)


class TestOutcomeRecording:
    """Test recording outcomes of decisions."""

    def test_record_successful_outcome(self, tmp_path: Path):
        """Test recording a successful outcome."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        decision_id = runtime.decide(
            intent="Test action",
            options=[{"id": "a", "description": "Action A"}],
            chosen="a",
            reasoning="Test",
        )

        runtime.record_outcome(
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

        runtime.end_run(success=True)

    def test_record_failed_outcome(self, tmp_path: Path):
        """Test recording a failed outcome."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        decision_id = runtime.decide(
            intent="Test action",
            options=[{"id": "a", "description": "Action A"}],
            chosen="a",
            reasoning="Test",
        )

        runtime.record_outcome(
            decision_id=decision_id,
            success=False,
            error="API rate limited",
        )

        decision = runtime.current_run.decisions[0]
        assert decision.outcome is not None
        assert decision.outcome.success is False
        assert decision.outcome.error == "API rate limited"
        assert decision.was_successful is False

        runtime.end_run(success=False)

    def test_metrics_updated_on_outcome(self, tmp_path: Path):
        """Test that metrics are updated when outcomes are recorded."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        # Successful decision
        d1 = runtime.decide(
            intent="Action 1",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        runtime.record_outcome(d1, success=True, tokens_used=100)

        # Failed decision
        d2 = runtime.decide(
            intent="Action 2",
            options=[{"id": "b", "description": "B"}],
            chosen="b",
            reasoning="Test",
        )
        runtime.record_outcome(d2, success=False)

        metrics = runtime.current_run.metrics
        assert metrics.total_decisions == 2
        assert metrics.successful_decisions == 1
        assert metrics.failed_decisions == 1
        assert metrics.total_tokens == 100

        runtime.end_run(success=False)


class TestProblemReporting:
    """Test problem reporting."""

    def test_report_problem(self, tmp_path: Path):
        """Test reporting a problem."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        problem_id = runtime.report_problem(
            severity="critical",
            description="API is unavailable",
            root_cause="Service outage",
            suggested_fix="Implement fallback to cached data",
        )

        assert problem_id == "prob_0"
        assert len(runtime.current_run.problems) == 1

        problem = runtime.current_run.problems[0]
        assert problem.severity == "critical"
        assert problem.description == "API is unavailable"

        runtime.end_run(success=False)

    def test_problem_linked_to_decision(self, tmp_path: Path):
        """Test linking a problem to a decision."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        decision_id = runtime.decide(
            intent="Call API",
            options=[{"id": "call", "description": "Make API call"}],
            chosen="call",
            reasoning="Need data",
        )

        runtime.report_problem(
            severity="warning",
            description="API slow",
            decision_id=decision_id,
        )

        problem = runtime.current_run.problems[0]
        assert problem.decision_id == decision_id

        runtime.end_run(success=True)


class TestConvenienceMethods:
    """Test convenience methods."""

    def test_quick_decision(self, tmp_path: Path):
        """Test quick_decision for simple cases."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        runtime.quick_decision(
            intent="Log message",
            action="Write to stdout",
            reasoning="Standard logging",
        )

        decision = runtime.current_run.decisions[0]
        assert decision.intent == "Log message"
        assert len(decision.options) == 1
        assert decision.options[0].id == "action"

        runtime.end_run(success=True)

    def test_decide_and_execute_success(self, tmp_path: Path):
        """Test decide_and_execute with successful execution."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        def do_action():
            return {"computed": 42}

        decision_id, result = runtime.decide_and_execute(
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

        runtime.end_run(success=True)

    def test_decide_and_execute_failure(self, tmp_path: Path):
        """Test decide_and_execute with failed execution."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        def do_failing_action():
            raise ValueError("Something went wrong")

        with pytest.raises(ValueError, match="Something went wrong"):
            runtime.decide_and_execute(
                intent="Failing action",
                options=[{"id": "fail", "description": "Will fail"}],
                chosen="fail",
                reasoning="Test failure",
                executor=do_failing_action,
            )

        decision = runtime.current_run.decisions[0]
        assert decision.was_successful is False
        assert "Something went wrong" in decision.outcome.error

        runtime.end_run(success=False)


class TestNarrativeGeneration:
    """Test automatic narrative generation."""

    def test_default_narrative_success(self, tmp_path: Path):
        """Test default narrative for successful run."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        d1 = runtime.decide(
            intent="Action",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        runtime.record_outcome(d1, success=True)

        runtime.end_run(success=True)

        # Load and check narrative
        run = runtime.storage.load_run(runtime.storage.get_runs_by_goal("test_goal")[0])
        assert "completed successfully" in run.narrative

    def test_default_narrative_failure(self, tmp_path: Path):
        """Test default narrative for failed run."""
        runtime = Runtime(tmp_path)
        runtime.start_run("test_goal", "Test")

        d1 = runtime.decide(
            intent="Failing action",
            options=[{"id": "a", "description": "A"}],
            chosen="a",
            reasoning="Test",
        )
        runtime.record_outcome(d1, success=False, error="Test error")

        runtime.report_problem(
            severity="critical",
            description="Test critical issue",
        )

        runtime.end_run(success=False)

        run = runtime.storage.load_run(runtime.storage.get_runs_by_goal("test_goal")[0])
        assert "failed" in run.narrative
        assert "critical" in run.narrative.lower() or "Critical" in run.narrative
