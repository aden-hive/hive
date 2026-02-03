"""
tests for mcp validation schemas.

tests input validation for agent builder tools including
id format, string length limits, and required fields.
"""

import pytest
from pydantic import ValidationError

from framework.mcp.schemas import (
    ConstraintInput,
    EdgeInput,
    GoalInput,
    NodeInput,
    SessionInput,
    SuccessCriterionInput,
    validate_edge_input,
    validate_goal_input,
    validate_id_format,
    validate_node_input,
)


class TestIdValidation:
    """test id format validation"""

    def test_valid_id_simple(self):
        assert validate_id_format("my_node", "test") == "my_node"

    def test_valid_id_with_numbers(self):
        assert validate_id_format("node123", "test") == "node123"

    def test_valid_id_with_hyphens(self):
        assert validate_id_format("my-node-1", "test") == "my-node-1"

    def test_invalid_empty_id(self):
        with pytest.raises(ValueError) as exc:
            validate_id_format("", "test")
        assert "cannot be empty" in str(exc.value)

    def test_invalid_starts_with_number(self):
        with pytest.raises(ValueError) as exc:
            validate_id_format("123node", "test")
        assert "must start with a letter" in str(exc.value)

    def test_invalid_special_chars(self):
        with pytest.raises(ValueError) as exc:
            validate_id_format("my@node!", "test")
        assert "alphanumeric" in str(exc.value)

    def test_invalid_spaces(self):
        with pytest.raises(ValueError) as exc:
            validate_id_format("my node", "test")
        assert "alphanumeric" in str(exc.value)

    def test_invalid_too_long(self):
        long_id = "a" * 100
        with pytest.raises(ValueError) as exc:
            validate_id_format(long_id, "test")
        assert "max length" in str(exc.value)


class TestGoalInput:
    """test goal input validation"""

    def test_valid_goal(self):
        goal = GoalInput(
            goal_id="my_goal",
            name="Test Goal",
            description="A test goal description",
            success_criteria='[{"id": "sc1", "description": "test"}]',
        )
        assert goal.goal_id == "my_goal"
        assert goal.name == "Test Goal"

    def test_missing_name(self):
        with pytest.raises(ValidationError):
            GoalInput(
                goal_id="my_goal",
                name="",  # empty
                description="desc",
                success_criteria="[]",
            )

    def test_invalid_goal_id(self):
        with pytest.raises(ValidationError) as exc:
            GoalInput(
                goal_id="123invalid",  # starts with number
                name="Test",
                description="desc",
                success_criteria="[]",
            )
        assert "must start with a letter" in str(exc.value)

    def test_invalid_json_format(self):
        with pytest.raises(ValidationError) as exc:
            GoalInput(
                goal_id="goal",
                name="Test",
                description="desc",
                success_criteria="not json",  # invalid
            )
        assert "JSON" in str(exc.value)


class TestNodeInput:
    """test node input validation"""

    def test_valid_node(self):
        node = NodeInput(
            node_id="process_data",
            name="Process Data",
            description="Processes input data",
            node_type="llm_generate",
        )
        assert node.node_id == "process_data"
        assert node.node_type == "llm_generate"

    def test_invalid_node_type(self):
        with pytest.raises(ValidationError) as exc:
            NodeInput(
                node_id="node1",
                name="Test",
                description="desc",
                node_type="invalid_type",
            )
        assert "node_type must be one of" in str(exc.value)

    def test_valid_node_types(self):
        for node_type in ["llm_generate", "llm_tool_use", "router", "function"]:
            node = NodeInput(
                node_id="node1",
                name="Test",
                description="desc",
                node_type=node_type,
            )
            assert node.node_type == node_type

    def test_long_description_rejected(self):
        long_desc = "x" * 3000  # exceeds max
        with pytest.raises(ValidationError):
            NodeInput(
                node_id="node1",
                name="Test",
                description=long_desc,
                node_type="llm_generate",
            )


class TestEdgeInput:
    """test edge input validation"""

    def test_valid_edge(self):
        edge = EdgeInput(
            edge_id="edge1",
            source="node_a",
            target="node_b",
        )
        assert edge.edge_id == "edge1"
        assert edge.condition == "on_success"

    def test_invalid_condition(self):
        with pytest.raises(ValidationError) as exc:
            EdgeInput(
                edge_id="edge1",
                source="node_a",
                target="node_b",
                condition="invalid",
            )
        assert "condition must be one of" in str(exc.value)

    def test_valid_conditions(self):
        for cond in ["always", "on_success", "on_failure", "conditional", "llm_decide"]:
            edge = EdgeInput(
                edge_id="edge1",
                source="node_a",
                target="node_b",
                condition=cond,
            )
            assert edge.condition == cond

    def test_priority_bounds(self):
        # valid priority
        edge = EdgeInput(
            edge_id="edge1",
            source="a",
            target="b",
            priority=100,
        )
        assert edge.priority == 100

        # too high
        with pytest.raises(ValidationError):
            EdgeInput(
                edge_id="edge1",
                source="a",
                target="b",
                priority=2000,  # exceeds max
            )


class TestSuccessCriterionInput:
    """test success criterion validation"""

    def test_valid_criterion(self):
        sc = SuccessCriterionInput(
            id="sc_response_time",
            description="Response time under 5 seconds",
        )
        assert sc.id == "sc_response_time"
        assert sc.weight == 1.0

    def test_invalid_id(self):
        with pytest.raises(ValidationError):
            SuccessCriterionInput(
                id="123bad",  # starts with number
                description="test",
            )

    def test_weight_bounds(self):
        sc = SuccessCriterionInput(
            id="test",
            description="test",
            weight=50.0,
        )
        assert sc.weight == 50.0

        with pytest.raises(ValidationError):
            SuccessCriterionInput(
                id="test",
                description="test",
                weight=200.0,  # exceeds max
            )


class TestConstraintInput:
    """test constraint validation"""

    def test_valid_constraint(self):
        c = ConstraintInput(
            id="no_pii",
            description="No personal info",
        )
        assert c.id == "no_pii"
        assert c.constraint_type == "hard"

    def test_invalid_constraint_type(self):
        with pytest.raises(ValidationError) as exc:
            ConstraintInput(
                id="test",
                description="test",
                constraint_type="medium",  # invalid
            )
        assert "constraint_type must be one of" in str(exc.value)


class TestSessionInput:
    """test session input validation"""

    def test_valid_session(self):
        s = SessionInput(name="My Agent")
        assert s.name == "My Agent"

    def test_empty_name(self):
        with pytest.raises(ValidationError):
            SessionInput(name="")

    def test_long_name(self):
        with pytest.raises(ValidationError):
            SessionInput(name="x" * 200)  # exceeds max


class TestValidationFunctions:
    """test convenience validation functions"""

    def test_validate_goal_input_valid(self):
        valid, errors = validate_goal_input(
            goal_id="goal1",
            name="Test Goal",
            description="A description",
            success_criteria="[]",
        )
        assert valid is True
        assert errors == []

    def test_validate_goal_input_invalid(self):
        valid, errors = validate_goal_input(
            goal_id="123bad",  # invalid id
            name="Test",
            description="desc",
            success_criteria="[]",
        )
        assert valid is False
        assert len(errors) > 0

    def test_validate_node_input_valid(self):
        valid, errors = validate_node_input(
            node_id="node1",
            name="Test Node",
            description="desc",
            node_type="llm_generate",
        )
        assert valid is True
        assert errors == []

    def test_validate_node_input_invalid_type(self):
        valid, errors = validate_node_input(
            node_id="node1",
            name="Test",
            description="desc",
            node_type="bad_type",
        )
        assert valid is False

    def test_validate_edge_input_valid(self):
        valid, errors = validate_edge_input(
            edge_id="edge1",
            source="a",
            target="b",
        )
        assert valid is True

    def test_validate_edge_input_invalid_source(self):
        valid, errors = validate_edge_input(
            edge_id="edge1",
            source="123bad",  # invalid
            target="b",
        )
        assert valid is False
