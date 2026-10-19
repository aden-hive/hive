"""Tests for the validation_errors field on NodeResult.

(The former test_pydantic_validation.py covered an output_model / Pydantic
output-validation feature that was never wired into execution and has been
removed. validation_errors itself stays — it's read in the agent loop.)
"""

from framework.orchestrator.node import NodeResult


class TestNodeResultValidationErrors:
    """Tests for validation_errors field in NodeResult."""

    def test_noderesult_includes_validation_errors(self):
        """NodeResult should store validation errors."""
        result = NodeResult(
            success=False,
            error="validation failed",
            validation_errors=["count: field required", "priority: must be >= 1"],
        )

        assert len(result.validation_errors) == 2
        assert "count" in result.validation_errors[0]

    def test_noderesult_empty_validation_errors_by_default(self):
        """validation_errors should be empty list by default."""
        result = NodeResult(success=True, output={"key": "value"})

        assert result.validation_errors == []
