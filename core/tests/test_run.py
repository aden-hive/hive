"""
Test the run module.
"""

from datetime import datetime

from framework.schemas.decision import Decision, Option, Outcome
from framework.schemas.run import Run, RunMetrics, RunStatus, RunSummary


class TestRuntimeMetrics:
    """Test the RunMetrics class."""

    def test_success_rate(self):
        metrics = RunMetrics(
            total_decisions=10,
            successful_decisions=8,
            failed_decisions=2,
        )
        assert metrics.success_rate == 0.8

    def test_success_rate_zero_decisions(self):
        metrics = RunMetrics(
            total_decisions=0,
            successful_decisions=0,
            failed_decisions=0,
        )
        assert metrics.success_rate == 0.0


class TestRun:
    """Test the Run class."""

    def test_duration_ms(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        assert run.duration_ms == int((run.completed_at - run.started_at).total_seconds() * 1000)

    def test_add_decision(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        decision = Decision(
            id="test_decision",
            timestamp=datetime.now(),
            node_id="test_node",
            intent="Choose a greeting",
            options=[
                {"id": "hello", "description": "Say hello", "action_type": "generate"},
                {"id": "hi", "description": "Say hi", "action_type": "generate"},
            ],
        )
        run.add_decision(decision)
        assert run.metrics.total_decisions == 1
        assert run.metrics.nodes_executed == ["test_node"]

    def test_record_outcome(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
            metrics=RunMetrics(total_decisions=0, successful_decisions=0, failed_decisions=0),
        )
        decision = Decision(
            id="test_decision",
            timestamp=datetime.now(),
            node_id="test_node",
            intent="Choose a greeting",
            options=[
                Option(id="hello", description="Say hello", action_type="generate"),
                Option(id="hi", description="Say hi", action_type="generate"),
            ],
        )

        outcome = Outcome(
            success=True,
            tokens_used=10,
            latency_ms=100,
        )
        run.add_decision(decision)
        run.record_outcome(decision.id, outcome)

        assert run.decisions[0].outcome == outcome
        assert run.metrics.successful_decisions == 1
        assert run.metrics.failed_decisions == 0
        assert run.metrics.total_tokens == 10
        assert run.metrics.total_latency_ms == 100

    def test_add_problem(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        problem_id = run.add_problem(
            "Test problem",
            "Test problem description",
            "test_decision",
            "Test root cause",
            "Test suggested fix",
        )

        assert problem_id == f"prob_{len(run.problems) - 1}"

        problem = run.problems[0]
        assert problem.id == f"prob_{len(run.problems) - 1}"
        assert problem.severity == "Test problem"
        assert problem.description == "Test problem description"
        assert problem.decision_id == "test_decision"
        assert problem.root_cause == "Test root cause"
        assert problem.suggested_fix == "Test suggested fix"

    def test_complete(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        run.complete(RunStatus.COMPLETED, "Test narrative")
        assert run.status == RunStatus.COMPLETED
        assert run.narrative == "Test narrative"


class TestRunSummary:
    """Test the RunSummary class."""

    def test_from_run_basic(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )
        run.complete(RunStatus.COMPLETED, "Test narrative")

        summary = RunSummary.from_run(run)

        assert summary.run_id == "test_run"
        assert summary.goal_id == "test_goal"
        assert summary.status == RunStatus.COMPLETED
        assert summary.decision_count == 0
        assert summary.success_rate == 0.0
        assert summary.problem_count == 0
        assert summary.narrative == "Test narrative"

    def test_from_run_with_decisions(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

        successful_decision = Decision(
            id="decision_1",
            timestamp=datetime.now(),
            node_id="node_1",
            intent="Choose greeting",
            options=[
                Option(
                    id="opt_1",
                    description="Say hello",
                    action_type="generate",
                )
            ],
            chosen_option_id="opt_1",
        )
        successful_outcome = Outcome(
            success=True,
            tokens_used=10,
            latency_ms=100,
            summary="Successfully greeted user",
        )

        failed_decision = Decision(
            id="decision_2",
            timestamp=datetime.now(),
            node_id="node_2",
            intent="Process data",
            options=[
                Option(
                    id="opt_2",
                    description="Parse JSON",
                    action_type="tool_call",
                )
            ],
            chosen_option_id="opt_2",
        )
        failed_outcome = Outcome(
            success=False,
            error="Invalid JSON format",
            tokens_used=5,
            latency_ms=50,
        )

        run.add_decision(successful_decision)
        run.record_outcome("decision_1", successful_outcome)
        run.add_decision(failed_decision)
        run.record_outcome("decision_2", failed_outcome)
        run.complete(RunStatus.COMPLETED, "Test narrative")

        summary = RunSummary.from_run(run)

        assert summary.decision_count == 2
        assert summary.success_rate == 0.5
        assert len(summary.key_decisions) == 1
        assert len(summary.successes) == 1
        assert summary.successes[0] == "Successfully greeted user"

    def test_from_run_with_problems(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            started_at=datetime.now(),
            completed_at=datetime.now(),
        )

        run.add_problem(
            severity="critical",
            description="API timeout",
            decision_id="decision_1",
            root_cause="Network issue",
            suggested_fix="Add retry logic",
        )

        run.add_problem(
            severity="warning",
            description="High latency",
            decision_id="decision_2",
            root_cause="Large payload",
            suggested_fix="Optimize data size",
        )

        run.complete(RunStatus.COMPLETED, "Test narrative")

        summary = RunSummary.from_run(run)

        assert summary.problem_count == 2
        assert len(summary.critical_problems) == 1
        assert len(summary.warnings) == 1
        assert summary.critical_problems[0] == "API timeout"
        assert summary.warnings[0] == "High latency"
