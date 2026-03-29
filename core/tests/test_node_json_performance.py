"""Regression tests for JSON parsing performance and blocking behavior.

Run with:
    cd core
    pytest tests/test_node_json_performance.py -v
"""

import json
import time

from framework.graph.node import find_json_object

# Test inputs

LARGE_JSON_SIZE = 500_000  # 500KB
LARGE_TEXT_SIZE = 1_000_000  # 1MB


def generate_large_json(size_bytes: int) -> str:
    """Generate a large valid JSON string."""
    data = {"data": "x" * (size_bytes - 20)}
    return json.dumps(data)


def generate_large_text(size_bytes: int) -> str:
    """Generate large non-JSON text."""
    return "x" * size_bytes


class TestJsonPerformance:
    """Test performance characteristics of find_json_object."""

    def test_large_valid_json_performance(self):
        """Ensure parsing large valid JSON is fast (O(n))."""
        large_json = generate_large_json(LARGE_JSON_SIZE)
        input_text = f"prefix {large_json} suffix"

        start = time.perf_counter()
        result = find_json_object(input_text)
        duration = time.perf_counter() - start

        assert result == large_json
        # Should be very fast (< 0.5s for 500KB)
        assert duration < 0.5, f"Parsing took too long: {duration:.4f}s"

    def test_large_non_json_performance(self):
        """Ensure scanning large non-JSON text allows early exit or fast failure."""
        large_text = generate_large_text(LARGE_TEXT_SIZE)

        start = time.perf_counter()
        result = find_json_object(large_text)
        duration = time.perf_counter() - start

        assert result is None
        # Should be extremely fast (early exit on no '{')
        assert duration < 0.1, f"Scanning took too long: {duration:.4f}s"

    def test_worst_case_performance(self):
        """Test worst-case input: many nested braces."""
        # Note: New implementation limits nesting depth, so this should fail fast
        # or handle it gracefully without O(n^2) behavior
        nested = "{" * 1000 + "}" * 1000

        start = time.perf_counter()
        find_json_object(nested)
        duration = time.perf_counter() - start

        # Valid JSON (nested empty dicts technically, but here just braces)
        # Actually "{"*N is not valid JSON key-value, so it should return None
        # unless we formed valid {"a":{"b":...}}
        # But this tests the scanner performance
        assert duration < 0.5, f"Worst-case scan took too long: {duration:.4f}s"
