"""Tests for edge condition context-key precedence.

Verifies that memory keys cannot shadow reserved context keys
(output, result, true, false) during conditional-edge evaluation.
"""

from framework.graph.edge import EdgeCondition, EdgeSpec


class TestConditionContextShadowing:
    """Memory keys must not overwrite reserved context variables."""

    def test_memory_result_does_not_shadow_output_result(self):
        """A memory key 'result' must not override output.get('result')."""
        edge = EdgeSpec(
            id="e1",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="result == 'current'",
        )
        output = {"result": "current"}
        memory = {"result": "stale_memory_value"}

        # 'result' in the context should be output.get("result"),
        # not the memory value.
        assert edge._evaluate_condition(output, memory) is True

    def test_memory_output_does_not_shadow_output_dict(self):
        """A memory key named 'output' must not replace the output dict."""
        edge = EdgeSpec(
            id="e2",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr='output.get("status") == "done"',
        )
        output = {"status": "done"}
        memory = {"output": "some_string"}

        assert edge._evaluate_condition(output, memory) is True

    def test_memory_true_does_not_shadow_boolean(self):
        """A memory key named 'true' must not replace the boolean True."""
        edge = EdgeSpec(
            id="e3",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="true",
        )
        output = {}
        memory = {"true": 0}  # Would be falsy if it shadowed

        assert edge._evaluate_condition(output, memory) is True

    def test_memory_false_does_not_shadow_boolean(self):
        """A memory key named 'false' must not replace the boolean False."""
        edge = EdgeSpec(
            id="e4",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="false",
        )
        output = {}
        memory = {"false": 1}  # Would be truthy if it shadowed

        assert edge._evaluate_condition(output, memory) is False

    def test_non_reserved_memory_keys_still_accessible(self):
        """Normal (non-reserved) memory keys should still be directly accessible."""
        edge = EdgeSpec(
            id="e5",
            source="a",
            target="b",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr="confidence > 0.5",
        )
        output = {}
        memory = {"confidence": 0.9}

        assert edge._evaluate_condition(output, memory) is True
