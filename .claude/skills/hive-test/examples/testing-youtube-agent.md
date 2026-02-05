# Example: Testing a YouTube Research Agent

This example walks through testing a YouTube research agent that finds relevant videos based on a topic.

## Prerequisites

- Agent built with building-agents skill at `exports/youtube-research/`
- Goal defined with success criteria and constraints

## Step 1: Load the Goal

First, load the goal that was defined during the Goal stage:

```json
{
    "id": "youtube-research",
    "name": "YouTube Research Agent",
    "description": "Find relevant YouTube videos on a given topic",
    "success_criteria": [
        {
            "id": "find_videos",
            "description": "Find 3-5 relevant videos",
            "metric": "video_count",
            "target": "3-5",
            "weight": 1.0
        },
        {
            "id": "relevance",
            "description": "Videos must be relevant to the topic",
            "metric": "relevance_score",
            "target": ">0.8",
            "weight": 0.8
        }
    ],
    "constraints": [
        {
            "id": "api_limits",
            "description": "Must not exceed YouTube API rate limits",
            "constraint_type": "hard",
            "category": "technical"
        },
        {
            "id": "content_safety",
            "description": "Must filter out inappropriate content",
            "constraint_type": "hard",
            "category": "safety"
        }
    ]
}
```

## Step 2: Get Constraint Test Guidelines

During the Goal stage (or early Eval), get test guidelines for constraints:

```python
result = generate_constraint_tests(
    goal_id="youtube-research",
    goal_json='<goal JSON above>',
    agent_path="exports/youtube-research"
)
```

**The result contains guidelines (not generated tests):**
- `output_file`: Where to write tests
- `file_header`: Imports and fixtures to use
- `test_template`: Format for test functions
- `constraints_formatted`: The constraints to test
- `test_guidelines`: Rules for writing tests

## Step 3: Write Constraint Tests

Using the guidelines, write tests directly with the Write tool:

```python
# Write constraint tests using the provided file_header and guidelines
Write(
    file_path="exports/youtube-research/tests/test_constraints.py",
    content='''
"""Constraint tests for youtube-research agent."""

import os
import pytest
from exports.youtube_research import default_agent


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required for real testing."
)


@pytest.mark.asyncio
async def test_constraint_api_limits_respected():
    """Verify API rate limits are not exceeded."""
    import time
    mock_mode = bool(os.environ.get("MOCK_MODE"))

    for i in range(10):
        result = await default_agent.run({"topic": f"test_{i}"}, mock_mode=mock_mode)
        time.sleep(0.1)

    # Should complete without rate limit errors
    assert "rate limit" not in str(result).lower()


@pytest.mark.asyncio
async def test_constraint_content_safety_filter():
    """Verify inappropriate content is filtered."""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({"topic": "general topic"}, mock_mode=mock_mode)

    for video in result.videos:
        assert video.safe_for_work is True
        assert video.age_restricted is False
'''
)
```

## Step 4: Get Success Criteria Test Guidelines

After the agent is built, get success criteria test guidelines:

```python
result = generate_success_tests(
    goal_id="youtube-research",
    goal_json='<goal JSON>',
    node_names="search_node,filter_node,rank_node,format_node",
    tool_names="youtube_search,video_details,channel_info",
    agent_path="exports/youtube-research"
)
```

## Step 5: Write Success Criteria Tests

Using the guidelines, write success criteria tests:

```python
Write(
    file_path="exports/youtube-research/tests/test_success_criteria.py",
    content='''
"""Success criteria tests for youtube-research agent."""

import os
import pytest
from exports.youtube_research import default_agent


pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required for real testing."
)


@pytest.mark.asyncio
async def test_find_videos_happy_path():
    """Test finding videos for a common topic."""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({"topic": "machine learning"}, mock_mode=mock_mode)

    assert result.success
    assert 3 <= len(result.videos) <= 5
    assert all(v.title for v in result.videos)
    assert all(v.video_id for v in result.videos)


@pytest.mark.asyncio
async def test_find_videos_minimum_boundary():
    """Test at minimum threshold (3 videos)."""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({"topic": "niche topic xyz"}, mock_mode=mock_mode)

    assert len(result.videos) >= 3


@pytest.mark.asyncio
async def test_relevance_score_threshold():
    """Test relevance scoring meets threshold."""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({"topic": "python programming"}, mock_mode=mock_mode)

    for video in result.videos:
        assert video.relevance_score > 0.8


@pytest.mark.asyncio
async def test_find_videos_no_results_graceful():
    """Test graceful handling of no results."""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({"topic": "xyznonexistent123"}, mock_mode=mock_mode)

    # Should not crash, return empty or message
    assert result.videos == [] or result.message
'''
)
```

## Step 6: Run All Tests

Execute all tests:

```python
result = run_tests(
    goal_id="youtube-research",
    agent_path="exports/youtube-research",
    test_types='["all"]',
    parallel=4
)
```

**Results:**

```json
{
    "goal_id": "youtube-research",
    "overall_passed": false,
    "summary": {
        "total": 6,
        "passed": 5,
        "failed": 1,
        "pass_rate": "83.3%"
    },
    "duration_ms": 4521,
    "results": [
        {"test_id": "test_constraint_api_001", "passed": true, "duration_ms": 1234},
        {"test_id": "test_constraint_content_001", "passed": true, "duration_ms": 456},
        {"test_id": "test_success_001", "passed": true, "duration_ms": 789},
        {"test_id": "test_success_002", "passed": true, "duration_ms": 654},
        {"test_id": "test_success_003", "passed": true, "duration_ms": 543},
        {"test_id": "test_success_004", "passed": false, "duration_ms": 845,
         "error_category": "IMPLEMENTATION_ERROR",
         "error_message": "TypeError: 'NoneType' object has no attribute 'videos'"}
    ]
}
```

## Step 7: Debug the Failed Test

```python
result = debug_test(
    goal_id="youtube-research",
    test_name="test_find_videos_no_results_graceful",
    agent_path="exports/youtube-research"
)
```

**Debug Output:**

```json
{
    "test_id": "test_success_004",
    "test_name": "test_find_videos_no_results_graceful",
    "input": {"topic": "xyznonexistent123"},
    "expected": "Empty list or message",
    "actual": {"error": "TypeError: 'NoneType' object has no attribute 'videos'"},
    "passed": false,
    "error_message": "TypeError: 'NoneType' object has no attribute 'videos'",
    "error_category": "IMPLEMENTATION_ERROR",
    "stack_trace": "Traceback (most recent call last):\n  File \"filter_node.py\", line 42\n    for video in result.videos:\nTypeError: 'NoneType' object has no attribute 'videos'",
    "logs": [
        {"timestamp": "2026-01-20T10:00:01", "node": "search_node", "level": "INFO", "msg": "Searching for: xyznonexistent123"},
        {"timestamp": "2026-01-20T10:00:02", "node": "search_node", "level": "WARNING", "msg": "No results found"},
        {"timestamp": "2026-01-20T10:00:02", "node": "filter_node", "level": "ERROR", "msg": "NoneType error"}
    ],
    "runtime_data": {
        "execution_path": ["start", "search_node", "filter_node"],
        "node_outputs": {
            "search_node": null
        }
    },
    "suggested_fix": "Add null check in filter_node before accessing .videos attribute",
    "iteration_guidance": {
        "stage": "Agent",
        "action": "Fix the code in nodes/edges",
        "restart_required": false,
        "description": "The goal is correct, but filter_node doesn't handle null results from search_node."
    }
}
```

## Step 8: Iterate Based on Category

Since this is an **IMPLEMENTATION_ERROR**, we:

1. **Don't restart** the Goal → Agent → Eval flow
2. **Fix the agent** using building-agents skill:
   - Modify `filter_node` to handle null results
3. **Re-run Eval** (tests only)

### Fix in building-agents:

```python
# Update the filter_node to handle null
add_node(
    node_id="filter_node",
    name="Filter Node",
    description="Filter and rank videos",
    node_type="function",
    input_keys=["search_results"],
    output_keys=["filtered_videos"],
    system_prompt="""
    Filter videos by relevance.
    IMPORTANT: Handle case where search_results is None or empty.
    Return empty list if no results.
    """
)
```

### Re-export and re-test:

```python
# Re-export the fixed agent
export_graph(path="exports/youtube-research")

# Re-run tests
result = run_tests(
    goal_id="youtube-research",
    agent_path="exports/youtube-research",
    test_types='["all"]'
)
```

**Updated Results:**

```json
{
    "goal_id": "youtube-research",
    "overall_passed": true,
    "summary": {
        "total": 6,
        "passed": 6,
        "failed": 0,
        "pass_rate": "100.0%"
    }
}
```

## Summary

1. **Got guidelines** for constraint tests during Goal stage
2. **Wrote** constraint tests using Write tool
3. **Got guidelines** for success criteria tests during Eval stage
4. **Wrote** success criteria tests using Write tool
5. **Ran** tests in parallel
6. **Debugged** the one failure
7. **Categorized** as IMPLEMENTATION_ERROR
8. **Fixed** the agent (not the goal)
9. **Re-ran** Eval only (didn't restart full flow)
10. **Passed** all tests

The agent is now validated and ready for production use.
