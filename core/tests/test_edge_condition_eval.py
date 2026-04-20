"""Tests for EdgeSpec._evaluate_condition — validates that NameError
from undefined variables in condition expressions is raised as ValueError
instead of being silently swallowed.

Covers: successful evaluation, undefined variable detection, general
exception fallback, empty expression, buffer key access, and helpful
error context in the raised ValueError.
"""

import pytest

from framework.orchestrator.edge import EdgeCondition, EdgeSpec


def _make_edge(condition_expr: str, edge_id: str = "test-edge") -> EdgeSpec:
    """Helper to build a CONDITIONAL edge."""
    return EdgeSpec(
        id=edge_id,
        source="src",
        target="tgt",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr=condition_expr,
    )


# ---------------------------------------------------------------------------
# Successful evaluation (baseline — no regressions)
# ---------------------------------------------------------------------------


class TestConditionEvalSuccess:
    @pytest.mark.asyncio
    async def test_simple_true_expression(self):
        edge = _make_edge("result == 'ok'")
        assert await edge.should_traverse(
            source_success=True,
            source_output={"result": "ok"},
            buffer_data={},
        )

    @pytest.mark.asyncio
    async def test_simple_false_expression(self):
        edge = _make_edge("result == 'ok'")
        assert not await edge.should_traverse(
            source_success=True,
            source_output={"result": "fail"},
            buffer_data={},
        )

    @pytest.mark.asyncio
    async def test_buffer_key_access(self):
        """Buffer keys are unpacked into the context and accessible directly."""
        edge = _make_edge("dispatch_plan == 'reassign'")
        assert await edge.should_traverse(
            source_success=True,
            source_output={},
            buffer_data={"dispatch_plan": "reassign"},
        )

    @pytest.mark.asyncio
    async def test_output_dict_access(self):
        edge = _make_edge("output.get('confidence', 0) > 0.5")
        assert await edge.should_traverse(
            source_success=True,
            source_output={"confidence": 0.9},
            buffer_data={},
        )

    @pytest.mark.asyncio
    async def test_empty_expression_returns_true(self):
        """An edge with no condition_expr always evaluates to True."""
        edge = _make_edge("")
        assert await edge.should_traverse(
            source_success=True,
            source_output={},
            buffer_data={},
        )

    @pytest.mark.asyncio
    async def test_none_expression_returns_true(self):
        edge = EdgeSpec(
            id="e",
            source="s",
            target="t",
            condition=EdgeCondition.CONDITIONAL,
            condition_expr=None,
        )
        assert await edge.should_traverse(
            source_success=True,
            source_output={},
            buffer_data={},
        )


# ---------------------------------------------------------------------------
# NameError → ValueError (the core fix for #6324)
# ---------------------------------------------------------------------------


class TestConditionNameError:
    @pytest.mark.asyncio
    async def test_typo_in_variable_raises_value_error(self):
        """A typo like 'dispach_plan' (missing 't') must raise, not silently return False."""
        edge = _make_edge("'reassignment' in str(dispach_plan)", edge_id="check-dispatch")
        with pytest.raises(ValueError, match="undefined variable"):
            await edge.should_traverse(
                source_success=True,
                source_output={},
                buffer_data={"dispatch_plan": "reassignment"},
            )

    @pytest.mark.asyncio
    async def test_error_message_includes_edge_id(self):
        edge = _make_edge("nonexistent_var > 0", edge_id="my-edge-42")
        with pytest.raises(ValueError, match="my-edge-42"):
            await edge.should_traverse(
                source_success=True,
                source_output={},
                buffer_data={},
            )

    @pytest.mark.asyncio
    async def test_error_message_includes_expression(self):
        edge = _make_edge("nonexistent_var > 0")
        with pytest.raises(ValueError, match="nonexistent_var > 0"):
            await edge.should_traverse(
                source_success=True,
                source_output={},
                buffer_data={},
            )

    @pytest.mark.asyncio
    async def test_error_message_includes_available_keys(self):
        edge = _make_edge("wrong_key == 1")
        with pytest.raises(ValueError, match="dispatch_plan") as exc_info:
            await edge.should_traverse(
                source_success=True,
                source_output={"result": "ok"},
                buffer_data={"dispatch_plan": "go"},
            )
        # Verify the original NameError is chained
        assert exc_info.value.__cause__ is not None
        assert isinstance(exc_info.value.__cause__, NameError)

    @pytest.mark.asyncio
    async def test_completely_undefined_variable(self):
        """Even with empty buffer + output, NameError must still raise."""
        edge = _make_edge("ghost_variable")
        with pytest.raises(ValueError, match="undefined variable"):
            await edge.should_traverse(
                source_success=True,
                source_output={},
                buffer_data={},
            )


# ---------------------------------------------------------------------------
# General exceptions still fall back to False (non-NameError)
# ---------------------------------------------------------------------------


class TestConditionGeneralException:
    @pytest.mark.asyncio
    async def test_type_error_returns_false(self):
        """A type error in the expression still returns False (not raised)."""
        # Trying to add string and int → TypeError
        edge = _make_edge("result + 42")
        result = await edge.should_traverse(
            source_success=True,
            source_output={"result": "text"},
            buffer_data={},
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_zero_division_returns_false(self):
        edge = _make_edge("result / 0")
        result = await edge.should_traverse(
            source_success=True,
            source_output={"result": 10},
            buffer_data={},
        )
        assert result is False
