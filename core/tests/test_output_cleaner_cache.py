"""
Tests for OutputCleaner caching functionality.

Verifies that:
1. Cache keys are generated correctly
2. Successful cleanings are cached
3. Cache hits avoid LLM calls
4. Failure tracking works
5. Cache stats are accurate
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from framework.graph.output_cleaner import (
    OutputCleaner,
    CleansingConfig,
    _generate_cache_key,
    _heuristic_repair,
)


class MockNodeSpec:
    """Mock NodeSpec for testing."""

    def __init__(self, node_id: str, input_keys: list[str], input_schema: dict = None):
        self.id = node_id
        self.input_keys = input_keys
        self.input_schema = input_schema or {}


class TestCacheKeyGeneration:
    """Tests for cache key generation."""

    def test_same_inputs_produce_same_key(self):
        """Same inputs should produce identical cache keys."""
        key1 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Missing key: 'x'", "Type mismatch"],
            output_structure={"result": "value", "count": 42},
        )
        key2 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Missing key: 'x'", "Type mismatch"],
            output_structure={"result": "value", "count": 42},
        )
        assert key1 == key2

    def test_different_errors_produce_different_keys(self):
        """Different validation errors should produce different keys."""
        key1 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Missing key: 'x'"],
            output_structure={"result": "value"},
        )
        key2 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Type mismatch"],
            output_structure={"result": "value"},
        )
        assert key1 != key2

    def test_error_order_does_not_matter(self):
        """Error order should not affect cache key (sorted internally)."""
        key1 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Error A", "Error B"],
            output_structure={"x": 1},
        )
        key2 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Error B", "Error A"],
            output_structure={"x": 1},
        )
        assert key1 == key2

    def test_different_nodes_produce_different_keys(self):
        """Different source/target nodes should produce different keys."""
        key1 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-b",
            validation_errors=["Error"],
            output_structure={"x": 1},
        )
        key2 = _generate_cache_key(
            source_node_id="node-a",
            target_node_id="node-c",  # Different target
            validation_errors=["Error"],
            output_structure={"x": 1},
        )
        assert key1 != key2


class TestHeuristicRepair:
    """Tests for heuristic repair function."""

    def test_strips_markdown_code_blocks(self):
        """Should strip markdown code blocks."""
        text = '```json\n{"key": "value"}\n```'
        result = _heuristic_repair(text)
        assert result == {"key": "value"}

    def test_fixes_python_booleans(self):
        """Should convert Python True/False to JSON true/false."""
        text = '{"active": True, "deleted": False}'
        result = _heuristic_repair(text)
        assert result == {"active": True, "deleted": False}

    def test_fixes_python_none(self):
        """Should convert Python None to JSON null."""
        text = '{"value": None}'
        result = _heuristic_repair(text)
        assert result == {"value": None}

    def test_handles_non_json_string(self):
        """Should return None for non-JSON strings."""
        result = _heuristic_repair("not json at all")
        assert result is None

    def test_handles_non_string_input(self):
        """Should return None for non-string input."""
        result = _heuristic_repair(123)
        assert result is None


class TestOutputCleanerCache:
    """Tests for OutputCleaner caching behavior."""

    @pytest.fixture
    def cleaner(self):
        """Create an OutputCleaner with caching enabled."""
        config = CleansingConfig(
            enabled=True,
            cache_successful_patterns=True,
            max_cache_size=100,
            max_failure_count=3,
            cache_ttl_seconds=3600,
        )
        # Create cleaner without LLM (we'll mock it)
        cleaner = OutputCleaner(config, llm_provider=None)
        return cleaner

    @pytest.fixture
    def mock_llm(self):
        """Create a mock LLM provider."""
        mock = MagicMock()
        mock.complete.return_value = MagicMock(
            content='{"topic": "test", "summary": "cleaned"}'
        )
        return mock

    def test_cache_stores_successful_heuristic_fix(self, cleaner):
        """Successful heuristic repairs should be cached."""
        target_spec = MockNodeSpec("target-node", ["topic", "summary"])

        # Output with JSON string that needs heuristic repair
        output = {"topic": '{"topic": "nested"}', "summary": "test"}

        # First call - should apply heuristic and cache
        result = cleaner.clean_output(
            output=output,
            source_node_id="source-node",
            target_node_spec=target_spec,
            validation_errors=["Key 'topic' contains JSON string"],
        )

        # Check that cache was populated
        assert len(cleaner.success_cache) == 1
        assert cleaner.cache_hits == 0
        assert cleaner.cache_misses == 1

    def test_cache_hit_on_repeated_pattern(self, cleaner, mock_llm):
        """Same error pattern should hit cache on second call."""
        cleaner.llm = mock_llm
        target_spec = MockNodeSpec("target-node", ["data"])

        output = {"data": "not-a-dict"}
        errors = ["Type mismatch: expected dict"]

        # Manually populate cache to simulate previous success
        cache_key = _generate_cache_key(
            "source-node", "target-node", errors, output
        )
        cleaner.success_cache[cache_key] = {
            "transformation": {
                "type": "heuristic",
                "fixed_keys": [],
                "template": {"expected_keys": ["data"]},
            },
            "timestamp": 1000000000,
        }

        # Now call clean_output - should hit cache
        with patch("time.time", return_value=1000000001):
            result = cleaner.clean_output(
                output=output,
                source_node_id="source-node",
                target_node_spec=target_spec,
                validation_errors=errors,
            )

        # LLM should NOT have been called (cache hit)
        mock_llm.complete.assert_not_called()
        assert cleaner.cache_hits == 1

    def test_failure_tracking_increments(self, cleaner, mock_llm):
        """Failed cleanings should be tracked."""
        # Make LLM return invalid response
        mock_llm.complete.return_value = MagicMock(content="not valid json {{{")
        cleaner.llm = mock_llm

        target_spec = MockNodeSpec("target-node", ["result"])
        output = {"result": "bad"}

        # Call clean_output - should fail and track failure
        result = cleaner.clean_output(
            output=output,
            source_node_id="source-node",
            target_node_spec=target_spec,
            validation_errors=["Missing key"],
        )

        # Check failure was tracked
        assert len(cleaner.failure_count) == 1
        failure_key = list(cleaner.failure_count.keys())[0]
        assert cleaner.failure_count[failure_key]["count"] == 1

    def test_skips_cleaning_after_max_failures(self, cleaner, mock_llm):
        """Should skip cleaning after max_failure_count failures."""
        cleaner.llm = mock_llm
        cleaner.config.max_failure_count = 2

        target_spec = MockNodeSpec("target-node", ["result"])
        output = {"result": "bad"}
        errors = ["Test error"]

        # Pre-populate failure count to simulate previous failures
        cache_key = _generate_cache_key(
            "source-node", "target-node", errors, output
        )
        cleaner.failure_count[cache_key] = {
            "count": 2,  # At max
            "last_error": "Previous error",
            "timestamp": 1000000000,
        }

        # Call clean_output - should skip and return raw
        result = cleaner.clean_output(
            output=output,
            source_node_id="source-node",
            target_node_spec=target_spec,
            validation_errors=errors,
        )

        # LLM should NOT have been called (skipped)
        mock_llm.complete.assert_not_called()
        assert cleaner.skipped_due_to_failures == 1
        # Should return raw output
        assert result == output

    def test_cache_eviction_on_max_size(self, cleaner):
        """Cache should evict old entries when max size reached."""
        cleaner.config.max_cache_size = 5

        # Fill cache to max
        import time
        for i in range(5):
            cleaner.success_cache[f"key_{i}"] = {
                "transformation": {"type": "test"},
                "timestamp": time.time() + i,
            }

        assert len(cleaner.success_cache) == 5

        # Add one more via _cache_transformation
        cleaner._cache_transformation(
            cache_key="new_key",
            original_output={"x": 1},
            cleaned_output={"x": 2},
            transform_type="test",
        )

        # Should have evicted oldest entries
        assert len(cleaner.success_cache) <= 5

    def test_clear_cache(self, cleaner):
        """clear_cache should reset all tracking."""
        # Add some data
        cleaner.success_cache["key1"] = {"data": "test"}
        cleaner.failure_count["key2"] = {"count": 1}

        stats = cleaner.clear_cache()

        assert stats["cache_entries_cleared"] == 1
        assert stats["failure_entries_cleared"] == 1
        assert len(cleaner.success_cache) == 0
        assert len(cleaner.failure_count) == 0


class TestOutputCleanerStats:
    """Tests for get_stats() method."""

    def test_stats_include_cache_metrics(self):
        """Stats should include comprehensive cache metrics."""
        config = CleansingConfig(enabled=True, cache_successful_patterns=True)
        cleaner = OutputCleaner(config)

        # Simulate some activity
        cleaner.cache_hits = 10
        cleaner.cache_misses = 5
        cleaner.cleansing_count = 3
        cleaner.skipped_due_to_failures = 2

        stats = cleaner.get_stats()

        assert stats["cache_hits"] == 10
        assert stats["cache_misses"] == 5
        assert stats["cache_hit_rate_percent"] == pytest.approx(66.7, rel=0.1)
        assert stats["llm_calls_saved"] == 10
        assert stats["total_cleanings"] == 3
        assert stats["skipped_due_to_failures"] == 2
        assert "uptime_seconds" in stats
        assert "config" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
