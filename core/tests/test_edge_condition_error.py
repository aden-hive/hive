"""Tests for EdgeCondition evaluation error handling (Issue #7393).

Ensures that evaluation failures in EdgeSpec conditions raise ConditionEvaluationError
rather than silently returning False and terminating graph execution without an error.
"""

import pytest
from framework.orchestrator import (
    ConditionEvaluationError,
    EdgeCondition,
    EdgeSpec,
)


class TestEdgeConditionErrorHandling:
    """Test suite for EdgeSpec condition evaluation errors."""

    def test_condition_evaluation_raises_error_on_invalid_attribute(self):
        """Accessing a non-existent property on result should raise ConditionEvaluationError."""
        edge = EdgeSpec(
            id="edge-1",
            source="node-a",
            target="node-b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="result.invalid_prop > 5",
        )
        output = {"result": "some_string"}
        buffer_data = {}

        with pytest.raises(ConditionEvaluationError) as exc_info:
            edge._evaluate_condition(output, buffer_data)

        err_msg = str(exc_info.value)
        assert "edge-1" in err_msg
        assert "result.invalid_prop > 5" in err_msg
        assert "Object has no attribute 'invalid_prop'" in err_msg or "AttributeError" in err_msg

    def test_condition_evaluation_raises_error_on_undefined_variable(self):
        """Referencing an undefined variable in context should raise ConditionEvaluationError."""
        edge = EdgeSpec(
            id="edge-2",
            source="node-a",
            target="node-b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="unknown_var == True",
        )

        with pytest.raises(ConditionEvaluationError) as exc_info:
            edge._evaluate_condition({}, {})

        err_msg = str(exc_info.value)
        assert "edge-2" in err_msg
        assert "unknown_var" in err_msg

    def test_condition_evaluation_raises_error_on_syntax_error(self):
        """Syntax errors in condition_expr should raise ConditionEvaluationError."""
        edge = EdgeSpec(
            id="edge-3",
            source="node-a",
            target="node-b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output['key' == ",
        )

        with pytest.raises(ConditionEvaluationError) as exc_info:
            edge._evaluate_condition({}, {})

        assert "edge-3" in str(exc_info.value)

    def test_condition_evaluation_succeds_on_valid_expr(self):
        """Valid condition expressions returning True/False should work normally."""
        edge_true = EdgeSpec(
            id="edge-true",
            source="node-a",
            target="node-b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.get('status') == 'success'",
        )
        edge_false = EdgeSpec(
            id="edge-false",
            source="node-a",
            target="node-b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="output.get('status') == 'failed'",
        )

        output = {"status": "success"}
        assert edge_true._evaluate_condition(output, {}) is True
        assert edge_false._evaluate_condition(output, {}) is False

    @pytest.mark.asyncio
    async def test_should_traverse_propagates_condition_evaluation_error(self):
        """should_traverse should propagate ConditionEvaluationError for CONDITIONAL edges."""
        edge = EdgeSpec(
            id="edge-async",
            source="node-a",
            target="node-b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="result.non_existent > 10",
        )

        with pytest.raises(ConditionEvaluationError):
            await edge.should_traverse(
                source_success=True,
                source_output={"result": 123},
                buffer_data={},
            )
