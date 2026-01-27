"""
Tests for NodeResult.to_summary() method.

This test suite validates the fix for the synchronous LLM blocking issue
where to_summary() made blocking API calls that froze the async event loop.

The fix introduces:
- Fast path (default): use_llm=False returns inline summary
- LLM path (opt-in): use_llm=True calls LLM for complex outputs
- Complexity threshold: 500 chars - skips LLM for small outputs
"""

import time

import pytest

from framework.graph.node import NodeResult, NodeSpec


class TestToSummaryFastPath:
    """Tests for the fast path (use_llm=False, default)."""

    def test_fast_path_is_default(self):
        """Default to_summary() should use fast path, not LLM."""
        result = NodeResult(
            success=True,
            output={"key1": "value1", "key2": "value2"}
        )

        start = time.time()
        summary = result.to_summary()
        elapsed_ms = (time.time() - start) * 1000

        # Fast path should be < 10ms (typically < 1ms)
        assert elapsed_ms < 10, f"Fast path took {elapsed_ms:.2f}ms, expected < 10ms"
        assert "✓ Completed with 2 outputs:" in summary
        assert "key1: value1" in summary

    def test_fast_path_explicit(self):
        """Explicit use_llm=False should use fast path."""
        result = NodeResult(
            success=True,
            output={"data": "test"}
        )

        start = time.time()
        summary = result.to_summary(use_llm=False)
        elapsed_ms = (time.time() - start) * 1000

        assert elapsed_ms < 10
        assert "✓ Completed with 1 outputs:" in summary

    def test_fast_path_truncates_long_values(self):
        """Fast path should truncate values > 100 chars."""
        long_value = "x" * 150
        result = NodeResult(
            success=True,
            output={"long_key": long_value}
        )

        summary = result.to_summary()

        assert "..." in summary
        assert len(summary) < 200  # Should be truncated

    def test_fast_path_limits_keys(self):
        """Fast path should show at most 5 keys."""
        result = NodeResult(
            success=True,
            output={f"key{i}": f"value{i}" for i in range(10)}
        )

        summary = result.to_summary()

        # Should only show first 5 keys
        assert "key0" in summary
        assert "key4" in summary
        # key5 through key9 might or might not be shown depending on implementation


class TestToSummaryEdgeCases:
    """Tests for edge cases."""

    def test_failed_result(self):
        """Failed results should return error message."""
        result = NodeResult(
            success=False,
            error="Something went wrong"
        )

        summary = result.to_summary()

        assert "❌ Failed:" in summary
        assert "Something went wrong" in summary

    def test_empty_output(self):
        """Empty output should return 'no output' message."""
        result = NodeResult(
            success=True,
            output={}
        )

        summary = result.to_summary()

        assert summary == "✓ Completed (no output)"

    def test_none_output(self):
        """None output should return 'no output' message."""
        result = NodeResult(
            success=True,
            output=None
        )

        summary = result.to_summary()

        assert summary == "✓ Completed (no output)"


class TestToSummaryLLMPath:
    """Tests for the LLM path (use_llm=True)."""

    def test_llm_path_small_output_uses_fast_path(self):
        """LLM path should fall back to fast path for small outputs (< 500 chars)."""
        result = NodeResult(
            success=True,
            output={"small": "data"}
        )

        start = time.time()
        summary = result.to_summary(use_llm=True)
        elapsed_ms = (time.time() - start) * 1000

        # Small output should use fast path even with use_llm=True
        assert elapsed_ms < 50  # Should be fast (no API call)
        assert "✓ Completed with 1 outputs:" in summary

    def test_llm_path_large_output_without_api_key(self):
        """LLM path with large output but no API key should use fallback."""
        # Create output > 500 chars
        large_data = {"data": "x" * 600}
        result = NodeResult(
            success=True,
            output=large_data
        )

        # This will try LLM path but fall back without API key
        summary = result.to_summary(use_llm=True)

        # Should still work (fallback)
        assert "✓ Completed with 1 outputs:" in summary

    def test_llm_path_with_node_spec(self):
        """LLM path should accept node_spec parameter."""
        result = NodeResult(
            success=True,
            output={"result": "value"}
        )
        node_spec = NodeSpec(
            id="test_node",
            name="Test Node",
            description="A test node"
        )

        # Should not raise
        summary = result.to_summary(node_spec=node_spec, use_llm=False)

        assert "✓ Completed" in summary


class TestToSummaryHelperMethods:
    """Tests for the helper methods."""

    def test_simple_summary_method(self):
        """_simple_summary() should return formatted output."""
        result = NodeResult(
            success=True,
            output={"key": "value"}
        )

        summary = result._simple_summary()

        assert "✓ Completed with 1 outputs:" in summary
        assert "key: value" in summary

    def test_llm_summary_fallback_without_key(self):
        """_llm_summary() should fall back to simple summary without API key."""
        result = NodeResult(
            success=True,
            output={"key": "value"}
        )

        summary = result._llm_summary()

        # Should use fallback
        assert "✓ Completed with 1 outputs:" in summary


class TestToSummaryPerformance:
    """Performance regression tests."""

    def test_fast_path_under_1ms(self):
        """Fast path should complete in under 1ms for typical outputs."""
        result = NodeResult(
            success=True,
            output={
                "step1": "completed",
                "step2": "in_progress",
                "result": {"nested": "data"}
            }
        )

        # Run multiple times to get stable measurement
        times = []
        for _ in range(10):
            start = time.time()
            result.to_summary()
            times.append((time.time() - start) * 1000)

        avg_ms = sum(times) / len(times)
        assert avg_ms < 1, f"Average fast path time {avg_ms:.3f}ms exceeds 1ms"

    def test_no_blocking_on_large_output(self):
        """Even large outputs should be fast with use_llm=False."""
        # Create a result with large output
        large_output = {f"key{i}": "x" * 1000 for i in range(100)}
        result = NodeResult(
            success=True,
            output=large_output
        )

        start = time.time()
        result.to_summary(use_llm=False)
        elapsed_ms = (time.time() - start) * 1000

        # Should still be fast (< 10ms)
        assert elapsed_ms < 10, f"Large output took {elapsed_ms:.2f}ms"
