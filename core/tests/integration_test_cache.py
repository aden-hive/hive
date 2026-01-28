#!/usr/bin/env python
"""
Integration test for OutputCleaner caching.

This script demonstrates the cache working in practice:
1. First call - cache miss, performs cleaning
2. Second call with same pattern - cache hit, skips cleaning
3. Shows stats proving LLM calls were saved

Run: python tests/integration_test_cache.py
"""

import json
import sys
from unittest.mock import MagicMock

# Add framework to path
sys.path.insert(0, ".")

from framework.graph.output_cleaner import OutputCleaner, CleansingConfig


class MockNodeSpec:
    """Mock NodeSpec for testing."""
    def __init__(self, node_id: str, input_keys: list[str]):
        self.id = node_id
        self.input_keys = input_keys
        self.input_schema = {}


def create_mock_llm():
    """Create a mock LLM that tracks calls."""
    mock = MagicMock()
    mock.call_count = 0

    def complete_side_effect(*args, **kwargs):
        mock.call_count += 1
        print(f"    [LLM CALLED - call #{mock.call_count}]")
        return MagicMock(content='{"topic": "cleaned topic", "summary": "cleaned summary"}')

    mock.complete.side_effect = complete_side_effect
    return mock


def test_cache_saves_llm_calls():
    """Test that cache hits actually skip LLM calls."""
    print("\n" + "="*60)
    print("TEST: Cache Saves LLM Calls")
    print("="*60)

    # Create cleaner with caching enabled
    config = CleansingConfig(
        enabled=True,
        cache_successful_patterns=True,
        log_cleanings=True,
    )

    mock_llm = create_mock_llm()
    cleaner = OutputCleaner(config, llm_provider=mock_llm)

    target_spec = MockNodeSpec("target-node", ["topic", "summary"])

    # Malformed output that needs LLM cleaning (not fixable by heuristic)
    malformed_output = {
        "wrong_key": "some value",
        "another_wrong": 123,
    }
    validation_errors = ["Missing required key: 'topic'", "Missing required key: 'summary'"]

    print("\n--- Call 1: Should be CACHE MISS, LLM called ---")
    result1 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )
    print(f"Result 1: {result1}")

    print("\n--- Call 2: Same pattern, should be CACHE HIT, NO LLM call ---")
    result2 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )
    print(f"Result 2: {result2}")

    print("\n--- Call 3: Same pattern again, should be CACHE HIT ---")
    result3 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )
    print(f"Result 3: {result3}")

    # Get stats
    stats = cleaner.get_stats()

    print("\n" + "-"*60)
    print("RESULTS:")
    print("-"*60)
    print(f"  Total LLM calls made: {mock_llm.call_count}")
    print(f"  Cache hits: {stats['cache_hits']}")
    print(f"  Cache misses: {stats['cache_misses']}")
    print(f"  Cache hit rate: {stats['cache_hit_rate_percent']}%")
    print(f"  LLM calls saved: {stats['llm_calls_saved']}")
    print(f"  Cache size: {stats['cache_size']}")

    # Verify
    assert mock_llm.call_count == 1, f"Expected 1 LLM call, got {mock_llm.call_count}"
    assert stats['cache_hits'] == 2, f"Expected 2 cache hits, got {stats['cache_hits']}"
    assert stats['cache_misses'] == 1, f"Expected 1 cache miss, got {stats['cache_misses']}"

    print("\n✅ TEST PASSED: Cache correctly saved 2 LLM calls!")
    return True


def test_heuristic_repair_cached():
    """Test that heuristic repairs are also cached."""
    print("\n" + "="*60)
    print("TEST: Heuristic Repairs Are Cached")
    print("="*60)

    config = CleansingConfig(
        enabled=True,
        cache_successful_patterns=True,
        log_cleanings=True,
    )

    # No LLM - only heuristic repair
    cleaner = OutputCleaner(config, llm_provider=None)

    target_spec = MockNodeSpec("target-node", ["data"])

    # Output with JSON string that heuristic can fix
    output_with_json_string = {
        "data": '{"nested": "value", "count": 42}',  # JSON string that should be parsed
    }
    validation_errors = ["Key 'data' contains JSON string"]

    print("\n--- Call 1: Heuristic repair ---")
    result1 = cleaner.clean_output(
        output=output_with_json_string,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )
    print(f"Result 1: {result1}")

    print("\n--- Call 2: Should use cached heuristic ---")
    result2 = cleaner.clean_output(
        output=output_with_json_string,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )
    print(f"Result 2: {result2}")

    stats = cleaner.get_stats()

    print("\n" + "-"*60)
    print("RESULTS:")
    print("-"*60)
    print(f"  Cache hits: {stats['cache_hits']}")
    print(f"  Cache misses: {stats['cache_misses']}")
    print(f"  Cache size: {stats['cache_size']}")

    assert stats['cache_size'] == 1, f"Expected 1 cache entry, got {stats['cache_size']}"

    print("\n✅ TEST PASSED: Heuristic repairs are cached!")
    return True


def test_failure_tracking():
    """Test that repeated failures are tracked and skipped."""
    print("\n" + "="*60)
    print("TEST: Failure Tracking Skips Repeated Failures")
    print("="*60)

    config = CleansingConfig(
        enabled=True,
        cache_successful_patterns=True,
        max_failure_count=2,  # Skip after 2 failures
        log_cleanings=True,
        fallback_to_raw=True,
    )

    # Mock LLM that always fails
    mock_llm = MagicMock()
    mock_llm.call_count = 0

    def failing_complete(*args, **kwargs):
        mock_llm.call_count += 1
        print(f"    [LLM CALLED - call #{mock_llm.call_count}] - returning invalid JSON")
        return MagicMock(content='this is not valid json {{{')

    mock_llm.complete.side_effect = failing_complete

    cleaner = OutputCleaner(config, llm_provider=mock_llm)

    target_spec = MockNodeSpec("target-node", ["result"])
    malformed_output = {"wrong": "data"}
    validation_errors = ["Missing key: 'result'"]

    print("\n--- Call 1: LLM fails ---")
    result1 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )

    print("\n--- Call 2: LLM fails again ---")
    result2 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )

    print("\n--- Call 3: Should SKIP (max failures reached) ---")
    result3 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )

    print("\n--- Call 4: Should SKIP again ---")
    result4 = cleaner.clean_output(
        output=malformed_output,
        source_node_id="source-node",
        target_node_spec=target_spec,
        validation_errors=validation_errors,
    )

    stats = cleaner.get_stats()

    print("\n" + "-"*60)
    print("RESULTS:")
    print("-"*60)
    print(f"  Total LLM calls: {mock_llm.call_count}")
    print(f"  Skipped due to failures: {stats['skipped_due_to_failures']}")
    print(f"  Tracked failure patterns: {stats['tracked_failure_patterns']}")

    assert mock_llm.call_count == 2, f"Expected 2 LLM calls (then skip), got {mock_llm.call_count}"
    assert stats['skipped_due_to_failures'] == 2, f"Expected 2 skips, got {stats['skipped_due_to_failures']}"

    print("\n✅ TEST PASSED: Failure tracking works - saved 2 wasted LLM calls!")
    return True


def test_different_patterns_not_confused():
    """Test that different error patterns don't share cache."""
    print("\n" + "="*60)
    print("TEST: Different Patterns Have Separate Cache Entries")
    print("="*60)

    config = CleansingConfig(
        enabled=True,
        cache_successful_patterns=True,
        log_cleanings=True,
    )

    mock_llm = create_mock_llm()
    cleaner = OutputCleaner(config, llm_provider=mock_llm)

    target_spec = MockNodeSpec("target-node", ["topic", "summary"])

    # Pattern A
    output_a = {"wrong_a": "value_a"}
    errors_a = ["Missing key: 'topic'"]

    # Pattern B (different errors)
    output_b = {"wrong_b": "value_b"}
    errors_b = ["Missing key: 'summary'"]

    print("\n--- Pattern A, Call 1 ---")
    cleaner.clean_output(output_a, "source", target_spec, errors_a)

    print("\n--- Pattern B, Call 1 (different pattern, should miss cache) ---")
    cleaner.clean_output(output_b, "source", target_spec, errors_b)

    print("\n--- Pattern A, Call 2 (should hit cache) ---")
    cleaner.clean_output(output_a, "source", target_spec, errors_a)

    print("\n--- Pattern B, Call 2 (should hit cache) ---")
    cleaner.clean_output(output_b, "source", target_spec, errors_b)

    stats = cleaner.get_stats()

    print("\n" + "-"*60)
    print("RESULTS:")
    print("-"*60)
    print(f"  Total LLM calls: {mock_llm.call_count}")
    print(f"  Cache entries: {stats['cache_size']}")
    print(f"  Cache hits: {stats['cache_hits']}")
    print(f"  Cache misses: {stats['cache_misses']}")

    assert mock_llm.call_count == 2, f"Expected 2 LLM calls (one per pattern), got {mock_llm.call_count}"
    assert stats['cache_size'] == 2, f"Expected 2 cache entries, got {stats['cache_size']}"
    assert stats['cache_hits'] == 2, f"Expected 2 cache hits, got {stats['cache_hits']}"

    print("\n✅ TEST PASSED: Different patterns correctly cached separately!")
    return True


if __name__ == "__main__":
    print("\n" + "#"*60)
    print("# OutputCleaner Cache Integration Tests")
    print("#"*60)

    all_passed = True

    try:
        test_cache_saves_llm_calls()
    except AssertionError as e:
        print(f"\n❌ FAILED: {e}")
        all_passed = False

    try:
        test_heuristic_repair_cached()
    except AssertionError as e:
        print(f"\n❌ FAILED: {e}")
        all_passed = False

    try:
        test_failure_tracking()
    except AssertionError as e:
        print(f"\n❌ FAILED: {e}")
        all_passed = False

    try:
        test_different_patterns_not_confused()
    except AssertionError as e:
        print(f"\n❌ FAILED: {e}")
        all_passed = False

    print("\n" + "#"*60)
    if all_passed:
        print("# ALL INTEGRATION TESTS PASSED ✅")
    else:
        print("# SOME TESTS FAILED ❌")
    print("#"*60 + "\n")

    sys.exit(0 if all_passed else 1)
