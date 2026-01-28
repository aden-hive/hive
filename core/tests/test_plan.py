"""Tests for plan.py - Plan enums and Pydantic models."""

import json

import pytest

from framework.graph.plan import (
    ActionSpec,
    ActionType,
    ApprovalDecision,
    ExecutionStatus,
    JudgmentAction,
    Plan,
    PlanStep,
    StepStatus,
)


class TestActionTypeEnum:
    """Tests for ActionType enum values."""

    def test_action_type_values_exist(self):
        """All 5 ActionType values exist."""
        assert ActionType.LLM_CALL.value == "llm_call"
        assert ActionType.TOOL_USE.value == "tool_use"
        assert ActionType.SUB_GRAPH.value == "sub_graph"
        assert ActionType.FUNCTION.value == "function"
        assert ActionType.CODE_EXECUTION.value == "code_execution"

    def test_action_type_count(self):
        """ActionType has exactly 5 members."""
        assert len(ActionType) == 5

    def test_action_type_string_enum(self):
        """ActionType is a string enum."""
        assert isinstance(ActionType.LLM_CALL, str)
        assert ActionType.LLM_CALL == "llm_call"


class TestStepStatusEnum:
    """Tests for StepStatus enum values."""

    def test_step_status_values_exist(self):
        """All 7 StepStatus values exist."""
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.AWAITING_APPROVAL.value == "awaiting_approval"
        assert StepStatus.IN_PROGRESS.value == "in_progress"
        assert StepStatus.COMPLETED.value == "completed"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"
        assert StepStatus.REJECTED.value == "rejected"

    def test_step_status_count(self):
        """StepStatus has exactly 7 members."""
        assert len(StepStatus) == 7

    def test_step_status_transition_pending_to_in_progress(self):
        """Status can change from PENDING to IN_PROGRESS."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            status=StepStatus.PENDING,
        )
        step.status = StepStatus.IN_PROGRESS
        assert step.status == StepStatus.IN_PROGRESS

    def test_step_status_transition_in_progress_to_completed(self):
        """Status can change from IN_PROGRESS to COMPLETED."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            status=StepStatus.IN_PROGRESS,
        )
        step.status = StepStatus.COMPLETED
        assert step.status == StepStatus.COMPLETED

    def test_step_status_transition_in_progress_to_failed(self):
        """Status can change from IN_PROGRESS to FAILED."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            status=StepStatus.IN_PROGRESS,
        )
        step.status = StepStatus.FAILED
        assert step.status == StepStatus.FAILED


class TestApprovalDecisionEnum:
    """Tests for ApprovalDecision enum values."""

    def test_approval_decision_values_exist(self):
        """All 4 ApprovalDecision values exist."""
        assert ApprovalDecision.APPROVE.value == "approve"
        assert ApprovalDecision.REJECT.value == "reject"
        assert ApprovalDecision.MODIFY.value == "modify"
        assert ApprovalDecision.ABORT.value == "abort"

    def test_approval_decision_count(self):
        """ApprovalDecision has exactly 4 members."""
        assert len(ApprovalDecision) == 4


class TestJudgmentActionEnum:
    """Tests for JudgmentAction enum values."""

    def test_judgment_action_values_exist(self):
        """All 4 JudgmentAction values exist."""
        assert JudgmentAction.ACCEPT.value == "accept"
        assert JudgmentAction.RETRY.value == "retry"
        assert JudgmentAction.REPLAN.value == "replan"
        assert JudgmentAction.ESCALATE.value == "escalate"

    def test_judgment_action_count(self):
        """JudgmentAction has exactly 4 members."""
        assert len(JudgmentAction) == 4


class TestExecutionStatusEnum:
    """Tests for ExecutionStatus enum values."""

    def test_execution_status_values_exist(self):
        """All 7 ExecutionStatus values exist."""
        assert ExecutionStatus.COMPLETED.value == "completed"
        assert ExecutionStatus.AWAITING_APPROVAL.value == "awaiting_approval"
        assert ExecutionStatus.NEEDS_REPLAN.value == "needs_replan"
        assert ExecutionStatus.NEEDS_ESCALATION.value == "needs_escalation"
        assert ExecutionStatus.REJECTED.value == "rejected"
        assert ExecutionStatus.ABORTED.value == "aborted"
        assert ExecutionStatus.FAILED.value == "failed"

    def test_execution_status_count(self):
        """ExecutionStatus has exactly 7 members."""
        assert len(ExecutionStatus) == 7


class TestPlanStepIsReady:
    """Tests for PlanStep.is_ready() method."""

    def test_plan_step_is_ready_no_deps(self):
        """Step with no dependencies is ready when PENDING."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=[],
            status=StepStatus.PENDING,
        )
        assert step.is_ready(set()) is True

    def test_plan_step_is_ready_deps_met(self):
        """Step is ready when all dependencies are completed."""
        step = PlanStep(
            id="step_2",
            description="Second step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_1"],
            status=StepStatus.PENDING,
        )
        assert step.is_ready({"step_1"}) is True

    def test_plan_step_not_ready_deps_missing(self):
        """Step is not ready when dependencies are incomplete."""
        step = PlanStep(
            id="step_2",
            description="Second step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_1", "step_3"],
            status=StepStatus.PENDING,
        )
        # Only step_1 completed, step_3 still pending
        assert step.is_ready({"step_1"}) is False

    def test_plan_step_not_ready_wrong_status(self):
        """Step is not ready if status is not PENDING."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=[],
            status=StepStatus.IN_PROGRESS,
        )
        assert step.is_ready(set()) is False

    def test_plan_step_not_ready_completed_status(self):
        """Completed step is not ready to execute again."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=[],
            status=StepStatus.COMPLETED,
        )
        assert step.is_ready(set()) is False

    def test_plan_step_is_ready_multiple_deps_all_met(self):
        """Step with multiple dependencies is ready when all are met."""
        step = PlanStep(
            id="step_4",
            description="Fourth step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_1", "step_2", "step_3"],
            status=StepStatus.PENDING,
        )
        assert step.is_ready({"step_1", "step_2", "step_3"}) is True


class TestPlanFromJson:
    """Tests for Plan.from_json() method."""

    def test_plan_from_json_string(self):
        """Parse Plan from JSON string."""
        json_str = json.dumps(
            {
                "id": "plan_1",
                "goal_id": "goal_1",
                "description": "Test plan",
                "steps": [
                    {
                        "id": "step_1",
                        "description": "First step",
                        "action": {
                            "action_type": "function",
                            "function_name": "do_something",
                        },
                    }
                ],
            }
        )

        plan = Plan.from_json(json_str)

        assert plan.id == "plan_1"
        assert plan.goal_id == "goal_1"
        assert len(plan.steps) == 1
        assert plan.steps[0].id == "step_1"

    def test_plan_from_json_dict(self):
        """Parse Plan from dict directly."""
        data = {
            "id": "plan_1",
            "goal_id": "goal_1",
            "description": "Test plan",
            "steps": [
                {
                    "id": "step_1",
                    "description": "First step",
                    "action": {
                        "action_type": "function",
                    },
                }
            ],
        }

        plan = Plan.from_json(data)

        assert plan.id == "plan_1"
        assert plan.goal_id == "goal_1"

    def test_plan_from_json_nested_plan_key(self):
        """Handle {"plan": {...}} wrapper from export_graph()."""
        data = {
            "plan": {
                "id": "plan_1",
                "goal_id": "goal_1",
                "description": "Test plan",
                "steps": [],
            }
        }

        plan = Plan.from_json(data)

        assert plan.id == "plan_1"

    def test_plan_from_json_action_type_conversion(self):
        """String action_type is converted to ActionType enum."""
        data = {
            "id": "plan_1",
            "goal_id": "goal_1",
            "description": "Test plan",
            "steps": [
                {
                    "id": "step_1",
                    "description": "LLM step",
                    "action": {
                        "action_type": "llm_call",
                        "prompt": "Hello",
                    },
                }
            ],
        }

        plan = Plan.from_json(data)

        assert plan.steps[0].action.action_type == ActionType.LLM_CALL

    def test_plan_from_json_all_action_types(self):
        """All action types are correctly converted."""
        action_types = ["llm_call", "tool_use", "sub_graph", "function", "code_execution"]

        for action_type in action_types:
            data = {
                "id": "plan",
                "goal_id": "goal",
                "description": "Test",
                "steps": [
                    {
                        "id": "step",
                        "description": "Step",
                        "action": {"action_type": action_type},
                    }
                ],
            }
            plan = Plan.from_json(data)
            assert plan.steps[0].action.action_type.value == action_type

    def test_from_json_invalid_action_type(self):
        """Unknown action_type raises ValueError."""
        data = {
            "id": "plan_1",
            "goal_id": "goal_1",
            "description": "Test plan",
            "steps": [
                {
                    "id": "step_1",
                    "description": "Invalid step",
                    "action": {
                        "action_type": "invalid_type",
                    },
                }
            ],
        }

        with pytest.raises(ValueError):
            Plan.from_json(data)

    def test_from_json_malformed_json_string(self):
        """Invalid JSON syntax raises parse error."""
        invalid_json = "{ invalid json }"

        with pytest.raises(json.JSONDecodeError):
            Plan.from_json(invalid_json)

    def test_from_json_missing_step_id(self):
        """Step without 'id' raises validation error."""
        data = {
            "id": "plan_1",
            "goal_id": "goal_1",
            "description": "Test plan",
            "steps": [
                {
                    "description": "Step without ID",
                    "action": {"action_type": "function"},
                }
            ],
        }

        with pytest.raises(KeyError):
            Plan.from_json(data)

    def test_from_json_wrong_type_for_steps(self):
        """Non-list steps value raises error."""
        data = {
            "id": "plan_1",
            "goal_id": "goal_1",
            "description": "Test plan",
            "steps": "not a list",
        }

        with pytest.raises(AttributeError):
            Plan.from_json(data)

    def test_from_json_empty_data(self):
        """Empty dict creates plan with defaults."""
        plan = Plan.from_json({})

        assert plan.id == "plan"
        assert plan.goal_id == ""
        assert plan.steps == []


class TestPlanMethods:
    """Tests for Plan instance methods."""

    @pytest.fixture
    def sample_plan(self):
        """Create a sample plan with multiple steps."""
        return Plan(
            id="test_plan",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="First step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    dependencies=[],
                    status=StepStatus.COMPLETED,
                    result={"data": "result1"},
                ),
                PlanStep(
                    id="step_2",
                    description="Second step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    dependencies=["step_1"],
                    status=StepStatus.PENDING,
                ),
                PlanStep(
                    id="step_3",
                    description="Third step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    dependencies=["step_1"],
                    status=StepStatus.FAILED,
                    error="Something went wrong",
                    attempts=3,
                ),
            ],
        )

    def test_plan_get_step(self, sample_plan):
        """Find step by ID."""
        step = sample_plan.get_step("step_2")

        assert step is not None
        assert step.id == "step_2"
        assert step.description == "Second step"

    def test_plan_get_step_not_found(self, sample_plan):
        """Returns None for missing step ID."""
        step = sample_plan.get_step("nonexistent")

        assert step is None

    def test_plan_get_ready_steps(self, sample_plan):
        """Filter steps ready to execute."""
        ready = sample_plan.get_ready_steps()

        assert len(ready) == 1
        assert ready[0].id == "step_2"

    def test_plan_get_completed_steps(self, sample_plan):
        """Filter completed steps."""
        completed = sample_plan.get_completed_steps()

        assert len(completed) == 1
        assert completed[0].id == "step_1"

    def test_plan_is_complete_false(self, sample_plan):
        """Plan is not complete when steps are pending/failed."""
        assert sample_plan.is_complete() is False

    def test_plan_is_complete_true(self):
        """Plan is complete when all steps are completed."""
        plan = Plan(
            id="test_plan",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="First step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    status=StepStatus.COMPLETED,
                ),
                PlanStep(
                    id="step_2",
                    description="Second step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    status=StepStatus.COMPLETED,
                ),
            ],
        )
        assert plan.is_complete() is True

    def test_plan_is_complete_empty(self):
        """Empty plan is considered complete."""
        plan = Plan(
            id="empty_plan",
            goal_id="goal_1",
            description="Empty plan",
            steps=[],
        )
        assert plan.is_complete() is True

    def test_plan_to_feedback_context(self, sample_plan):
        """Serializes context for replanning."""
        context = sample_plan.to_feedback_context()

        assert context["plan_id"] == "test_plan"
        assert context["revision"] == 1
        assert len(context["completed_steps"]) == 1
        assert context["completed_steps"][0]["id"] == "step_1"
        assert len(context["failed_steps"]) == 1
        assert context["failed_steps"][0]["id"] == "step_3"
        assert context["failed_steps"][0]["error"] == "Something went wrong"


class TestPlanRoundTrip:
    """Tests for Plan serialization round-trip."""

    def test_plan_round_trip_model_dump(self):
        """from_json(plan.model_dump()) preserves data."""
        original = Plan(
            id="plan_1",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="First step",
                    action=ActionSpec(
                        action_type=ActionType.LLM_CALL,
                        prompt="Hello world",
                    ),
                    dependencies=[],
                    expected_outputs=["greeting"],
                ),
            ],
            context={"key": "value"},
            revision=2,
        )

        # Round-trip through dict
        data = original.model_dump()
        restored = Plan.from_json(data)

        assert restored.id == original.id
        assert restored.goal_id == original.goal_id
        assert restored.description == original.description
        assert restored.context == original.context
        assert restored.revision == original.revision
        assert len(restored.steps) == len(original.steps)
        assert restored.steps[0].id == original.steps[0].id
        assert restored.steps[0].action.action_type == original.steps[0].action.action_type

    def test_plan_round_trip_json_string(self):
        """from_json(plan.model_dump_json()) preserves data."""
        original = Plan(
            id="plan_1",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="First step",
                    action=ActionSpec(
                        action_type=ActionType.TOOL_USE,
                        tool_name="my_tool",
                        tool_args={"arg1": "value1"},
                    ),
                    dependencies=[],
                ),
            ],
        )

        # Round-trip through JSON string
        json_str = original.model_dump_json()
        restored = Plan.from_json(json_str)

        assert restored.id == original.id
        assert len(restored.steps) == 1
        assert restored.steps[0].action.tool_name == "my_tool"

    def test_plan_step_serialization(self):
        """PlanStep serializes and deserializes correctly."""
        step = PlanStep(
            id="step_1",
            description="Test step",
            action=ActionSpec(
                action_type=ActionType.CODE_EXECUTION,
                code="print('hello')",
                language="python",
            ),
            inputs={"input1": "value1"},
            expected_outputs=["output1", "output2"],
            dependencies=["dep1", "dep2"],
            requires_approval=True,
            approval_message="Please approve",
        )

        # Serialize and deserialize
        data = step.model_dump()

        assert data["id"] == "step_1"
        assert data["action"]["action_type"] == "code_execution"
        assert data["action"]["code"] == "print('hello')"
        assert data["inputs"] == {"input1": "value1"}
        assert data["expected_outputs"] == ["output1", "output2"]
        assert data["dependencies"] == ["dep1", "dep2"]
        assert data["requires_approval"] is True
