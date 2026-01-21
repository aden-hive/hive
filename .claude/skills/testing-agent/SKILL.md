---
name: testing-agent
description: Run goal-based evaluation tests for agents. Use when you need to verify an agent meets its goals, debug failing tests, or iterate on agent improvements based on test results.
---

# Testing Agents (Python Service Architecture)

Run goal-based evaluation tests for agents built with the building-agents skill.

**Key Principle: Tests are Python files that directly import and test your agent**
- ✅ Tests created immediately in `exports/{agent}/tests/` directory
- ✅ Direct imports: `from exports.my_agent import default_agent`
- ✅ Use pytest framework - standard Python testing
- ✅ Full debugging with pdb, breakpoints, introspection
- ✅ No subprocess barriers - direct code access

## Architecture: Direct Python Testing

```
exports/my_agent/
├── __init__.py
├── agent.py              ← Agent to test
├── nodes/__init__.py
├── config.py
├── __main__.py
└── tests/                ← Tests live here
    ├── __init__.py
    ├── conftest.py       ← Shared fixtures
    ├── test_constraints.py
    ├── test_success_criteria.py
    └── test_edge_cases.py
```

**Tests import the agent directly:**
```python
from exports.my_agent import default_agent

async def test_happy_path():
    result = await default_agent.run({"query": "test"})
    assert result.success
    assert len(result.output) > 0
```

## Quick Start

1. **Check existing tests** - See what already exists
2. **Generate test files** - Create Python test files with pytest
3. **User reviews and approves** - Human approval for each test
4. **Run tests with pytest** - Standard Python testing workflow
5. **Debug failures** - Direct Python debugging (pdb, breakpoints)
6. **Iterate** - Edit agent code or tests directly

## ⚠️ API Key Requirement for Real Testing

**CRITICAL: Real LLM testing requires an API key.** Mock mode only validates structure and does NOT test actual agent behavior.

### Prerequisites

Before running agent tests, you MUST set your API key:

```bash
export ANTHROPIC_API_KEY="your-key-here"
```

**Why API keys are required:**
- Tests need to execute the agent's LLM nodes to validate behavior
- Mock mode bypasses LLM calls, providing no confidence in real-world performance
- Success criteria (personalization, reasoning quality, constraint adherence) can only be tested with real LLM calls

### Mock Mode Limitations

Mock mode (`--mock` flag or `mock_mode=True`) is **ONLY for structure validation**:

✓ Validates graph structure (nodes, edges, connections)
✓ Tests that code doesn't crash on execution
✗ Does NOT test LLM message generation
✗ Does NOT test reasoning or decision-making quality
✗ Does NOT test constraint validation (length limits, format rules)
✗ Does NOT test real API integrations or tool use
✗ Does NOT test personalization or content quality

**Bottom line:** If you're testing whether an agent achieves its goal, you MUST use a real API key.

### Enforcing API Key in Tests

When generating tests, **ALWAYS include API key checks**:

```python
import os
import pytest

# At the top of every test file
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required for real testing. Set ANTHROPIC_API_KEY or use MOCK_MODE=1 for structure validation only."
)


@pytest.fixture(scope="session", autouse=True)
def check_api_key():
    """Ensure API key is set for real testing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if os.environ.get("MOCK_MODE"):
            print("\n⚠️  Running in MOCK MODE - structure validation only")
            print("   This does NOT test LLM behavior or agent quality")
            print("   Set ANTHROPIC_API_KEY for real testing\n")
        else:
            pytest.fail(
                "\n❌ ANTHROPIC_API_KEY not set!\n\n"
                "Real testing requires an API key. Choose one:\n"
                "1. Set API key (RECOMMENDED):\n"
                "   export ANTHROPIC_API_KEY='your-key-here'\n"
                "2. Run structure validation only:\n"
                "   MOCK_MODE=1 pytest exports/{agent}/tests/\n\n"
                "Note: Mock mode does NOT validate agent behavior or quality."
            )
```

### User Communication

When the user asks to test an agent, **ALWAYS check for the API key first**:

```python
# Before running any tests
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("⚠️  No ANTHROPIC_API_KEY found!")
    print()
    print("Testing requires a real API key to validate agent behavior.")
    print()
    print("Options:")
    print("1. Set your API key (RECOMMENDED):")
    print("   export ANTHROPIC_API_KEY='your-key-here'")
    print()
    print("2. Run in mock mode (structure validation only):")
    print("   MOCK_MODE=1 pytest exports/{agent}/tests/")
    print()
    print("Mock mode does NOT test:")
    print("  - LLM message generation")
    print("  - Reasoning or decision quality")
    print("  - Constraint validation")
    print("  - Real API integrations")

    # Ask user what to do
    AskUserQuestion(...)
```

## The Three-Stage Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           GOAL STAGE                                     │
│  (building-agents skill)                                                 │
│                                                                          │
│  1. User defines goal with success_criteria and constraints             │
│  2. Goal written to agent.py immediately                                │
│  3. Generate CONSTRAINT TESTS → Write to tests/ → USER APPROVAL         │
│     Files created: exports/{agent}/tests/test_constraints.py            │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                          AGENT STAGE                                     │
│  (building-agents skill)                                                 │
│                                                                          │
│  Build nodes + edges, written immediately to files                      │
│  Constraint tests can run during development:                           │
│    $ pytest exports/{agent}/tests/test_constraints.py                   │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                           EVAL STAGE (this skill)                        │
│                                                                          │
│  1. Generate SUCCESS_CRITERIA TESTS → Write to tests/ → USER APPROVAL   │
│     Files created: exports/{agent}/tests/test_success_criteria.py       │
│  2. Run all tests with pytest:                                          │
│     $ pytest exports/{agent}/tests/ -v                                  │
│  3. On failure → Direct Python debugging                                │
│  4. Iterate: Edit agent code → Re-run pytest (instant feedback)         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Step-by-Step: Testing an Agent

### Step 1: Check Existing Tests

**ALWAYS check first** before generating new tests:

```python
Glob(pattern="exports/{agent_name}/tests/test_*.py")
```

This shows what test files already exist. If tests exist:
- Read them to see what's covered
- Ask user if they want to add more or run existing tests

### Step 2: Generate Constraint Tests (Goal Stage)

After goal is defined, generate constraint tests from the constraints:

```python
# Read the goal from agent.py
goal_code = Read(file_path=f"exports/{agent_name}/agent.py")

# Extract constraints from goal
# constraints = [...list of constraints from the goal...]

# Generate test file content with API key enforcement
test_file_content = f'''"""Constraint tests for {agent_name}.

These tests validate that the agent respects its defined constraints.
Generated from goal constraints during Goal stage.

REQUIRES: ANTHROPIC_API_KEY for real testing.
"""

import os
import pytest
from exports.{agent_name} import default_agent


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


@pytest.mark.asyncio
async def test_constraint_api_rate_limits(mock_mode):
    """Test: Agent respects API rate limits"""
    # Run multiple times quickly
    results = []
    for i in range(5):
        result = await default_agent.run({{"query": f"test{{i}}"}}, mock_mode=mock_mode)
        results.append(result)

    # Verify no rate limit errors
    for result in results:
        assert "rate limit" not in str(result.output).lower()
        assert result.success or "rate" not in result.error.lower()


@pytest.mark.asyncio
async def test_constraint_content_safety(mock_mode):
    """Test: Agent produces safe, appropriate content"""
    result = await default_agent.run({{"query": "test query"}}, mock_mode=mock_mode)

    # Verify no inappropriate content
    output_text = str(result.output).lower()
    unsafe_terms = ["explicit", "violent", "harmful"]
    assert not any(term in output_text for term in unsafe_terms)


# Add more constraint tests...
'''

# Write the test file
Write(
    file_path=f"exports/{agent_name}/tests/test_constraints.py",
    content=test_file_content
)

# Show user what was created
print(f"✅ Created constraint tests: exports/{agent_name}/tests/test_constraints.py")
print(f"   - test_constraint_api_rate_limits")
print(f"   - test_constraint_content_safety")
print(f"   - ... ({len(constraints)} total)")
```

**USER APPROVAL REQUIRED**: Show each test to the user and ask for approval.

```python
AskUserQuestion(
    questions=[{
        "question": "Approve constraint tests?",
        "header": "Test Approval",
        "options": [
            {
                "label": "Approve all (Recommended)",
                "description": "Tests look good, include in test suite"
            },
            {
                "label": "Review individually",
                "description": "Show each test for approval"
            },
            {
                "label": "Reject and regenerate",
                "description": "Tests need improvement"
            }
        ],
        "multiSelect": false
    }]
)
```

If user wants to modify tests, they can edit `test_constraints.py` directly.

### Step 3: Generate Success Criteria Tests (Eval Stage)

After agent is fully built, generate success criteria tests:

```python
# Read the goal and agent structure
goal_code = Read(file_path=f"exports/{agent_name}/agent.py")
nodes_code = Read(file_path=f"exports/{agent_name}/nodes/__init__.py")

# Extract success criteria from goal
# success_criteria = [...list of success criteria from goal...]

# Generate test file content with API key enforcement
test_file_content = f'''"""Success criteria tests for {agent_name}.

These tests validate that the agent achieves its defined success criteria.
Generated from goal success_criteria during Eval stage.

REQUIRES: ANTHROPIC_API_KEY for real testing - mock mode cannot validate success criteria.
"""

import os
import pytest
from exports.{agent_name} import default_agent


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


@pytest.mark.asyncio
async def test_success_find_relevant_results(mock_mode):
    """Test: Agent finds 3-5 relevant results"""
    result = await default_agent.run({{"topic": "machine learning"}}, mock_mode=mock_mode)

    assert result.success, f"Agent failed: {{result.error}}"
    assert "results" in result.output

    results_count = len(result.output["results"])
    assert 3 <= results_count <= 5, f"Expected 3-5 results, got {{results_count}}"

    # Verify relevance
    for item in result.output["results"]:
        assert "title" in item
        assert len(item["title"]) > 0


@pytest.mark.asyncio
async def test_success_response_quality(mock_mode):
    """Test: Agent provides high-quality, formatted output"""
    result = await default_agent.run({{"topic": "python tutorials"}}, mock_mode=mock_mode)

    assert result.success
    assert "output" in result.output

    output_text = result.output["output"]
    assert len(output_text) >= 100, "Output should be substantive"
    assert any(keyword in output_text.lower() for keyword in ["python", "tutorial"])


# Add more success criteria tests...
'''

# Write the test file
Write(
    file_path=f"exports/{agent_name}/tests/test_success_criteria.py",
    content=test_file_content
)

print(f"✅ Created success criteria tests: exports/{agent_name}/tests/test_success_criteria.py")
```

**USER APPROVAL REQUIRED**: Show each test and get approval.

### Step 4: Create Test Fixtures (conftest.py)

Create shared test fixtures for efficiency **with API key enforcement**:

```python
conftest_content = '''"""Shared test fixtures for {agent_name} tests."""

import os
import pytest
import asyncio


# Enforce API key requirement for real testing
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required for real testing. Set ANTHROPIC_API_KEY or use MOCK_MODE=1 for structure validation only."
)


@pytest.fixture(scope="session", autouse=True)
def check_api_key():
    """Ensure API key is set for real testing."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        if os.environ.get("MOCK_MODE"):
            print("\\n⚠️  Running in MOCK MODE - structure validation only")
            print("   This does NOT test LLM behavior or agent quality")
            print("   Set ANTHROPIC_API_KEY for real testing\\n")
        else:
            pytest.fail(
                "\\n❌ ANTHROPIC_API_KEY not set!\\n\\n"
                "Real testing requires an API key. Choose one:\\n"
                "1. Set API key (RECOMMENDED):\\n"
                "   export ANTHROPIC_API_KEY='your-key-here'\\n"
                "2. Run structure validation only:\\n"
                "   MOCK_MODE=1 pytest exports/{agent_name}/tests/\\n\\n"
                "Note: Mock mode does NOT validate agent behavior or quality."
            )


@pytest.fixture
def sample_inputs():
    """Sample inputs for testing."""
    return {{
        "simple": {{"query": "test"}},
        "complex": {{"query": "detailed multi-step query", "depth": 3}},
        "edge_case": {{"query": ""}},
    }}


@pytest.fixture
def mock_mode():
    """Check if running in mock mode."""
    return bool(os.environ.get("MOCK_MODE"))


# Add more shared fixtures as needed
'''

Write(
    file_path=f"exports/{agent_name}/tests/conftest.py",
    content=conftest_content
)
```

**IMPORTANT:** The conftest.py fixture will automatically check for API keys and fail tests if not set, preventing accidental mock testing.

### Step 5: Run Tests with Pytest

**IMPORTANT: Check for API key before running tests:**

```python
import os

# Always check API key first
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("⚠️  No ANTHROPIC_API_KEY found!")
    print()
    print("Testing requires a real API key to validate agent behavior.")
    print()
    print("Set your API key:")
    print("  export ANTHROPIC_API_KEY='your-key-here'")
    print()
    print("Or run in mock mode (structure validation only):")
    print(f"  MOCK_MODE=1 pytest exports/{agent_name}/tests/")
    print()
    # Ask user what to do or fail
    raise RuntimeError("API key required for testing")
```

Run tests using standard pytest commands:

```bash
# Ensure API key is set first!
$ export ANTHROPIC_API_KEY="your-key-here"

# Run all tests
$ pytest exports/{agent_name}/tests/ -v

# Run specific test file
$ pytest exports/{agent_name}/tests/test_constraints.py -v

# Run specific test
$ pytest exports/{agent_name}/tests/test_success_criteria.py::test_success_find_relevant_results -v

# Run with coverage
$ pytest exports/{agent_name}/tests/ --cov=exports/{agent_name} --cov-report=html

# Run in parallel (faster)
$ pytest exports/{agent_name}/tests/ -n 4

# Mock mode (structure validation only - NOT recommended for real testing)
$ MOCK_MODE=1 pytest exports/{agent_name}/tests/ -v
```

Use Bash tool to run pytest **with API key check**:

```python
import os

# Check for API key before running tests
if not os.environ.get("ANTHROPIC_API_KEY"):
    print("❌ Cannot run tests: ANTHROPIC_API_KEY not set")
    print("   Set with: export ANTHROPIC_API_KEY='your-key-here'")
    # Either fail or ask user
    AskUserQuestion(...)
else:
    Bash(
        command=f"cd /home/timothy/oss/hive && PYTHONPATH=core:exports:$PYTHONPATH pytest exports/{agent_name}/tests/ -v --tb=short",
        description="Run all tests for agent"
    )
```

**Output shows:**
```
============================= test session starts ==============================
collected 12 items

test_constraints.py::test_constraint_api_rate_limits PASSED           [  8%]
test_constraints.py::test_constraint_content_safety PASSED            [ 16%]
test_success_criteria.py::test_success_find_relevant_results FAILED  [ 25%]
test_success_criteria.py::test_success_response_quality PASSED       [ 33%]
...

=========================== 10 passed, 2 failed ============================
```

### Step 6: Debug Failed Tests

When tests fail, you have **direct Python debugging access**:

#### Option 1: Read the pytest output
```python
# The pytest output shows:
# - Which test failed
# - The assertion that failed
# - Stack trace with exact line numbers
# - Captured logs
```

#### Option 2: Run single test with full output
```python
Bash(
    command=f"cd /home/timothy/oss/hive && PYTHONPATH=core:exports:$PYTHONPATH pytest exports/{agent_name}/tests/test_success_criteria.py::test_success_find_relevant_results -vv -s",
    description="Run single test with full output"
)
```

#### Option 3: Add debugging code directly
```python
# User can edit test file to add debugging:
test_code = Read(file_path=f"exports/{agent_name}/tests/test_success_criteria.py")

# Show user the failing test and suggest adding:
# import pdb; pdb.set_trace()
# Or add print statements to inspect values
```

#### Option 4: Inspect agent execution
```python
# Tests can inspect agent structure (no API key needed for structure inspection):
inspection_test = '''
@pytest.mark.asyncio
async def test_debug_agent_structure():
    """Debug: Inspect agent structure (no API calls made)"""
    from exports.{agent_name} import default_agent

    print(f"Nodes: {{len(default_agent.nodes)}}")
    for node in default_agent.nodes:
        print(f"  - {{node.id}}: {{node.node_type}}")

    print(f"Edges: {{len(default_agent.edges)}}")
    for edge in default_agent.edges:
        print(f"  - {{edge.source}} -> {{edge.target}} ({{edge.condition}})")

    # This test always passes - it's for inspection
    assert True
'''
```

### Step 7: Categorize Errors

When a test fails, categorize the error to guide iteration:

```python
def categorize_test_failure(test_output, agent_code):
    """Categorize test failure to guide iteration."""

    # Read test output and agent code
    failure_info = {
        "test_name": "...",
        "error_message": "...",
        "stack_trace": "...",
    }

    # Pattern-based categorization
    if any(pattern in failure_info["error_message"].lower() for pattern in [
        "typeerror", "attributeerror", "keyerror", "valueerror",
        "null", "none", "undefined", "tool call failed"
    ]):
        category = "IMPLEMENTATION_ERROR"
        guidance = {
            "stage": "Agent",
            "action": "Fix the bug in agent code",
            "files_to_edit": ["agent.py", "nodes/__init__.py"],
            "restart_required": False,
            "description": "Code bug - fix and re-run tests"
        }

    elif any(pattern in failure_info["error_message"].lower() for pattern in [
        "assertion", "expected", "got", "should be", "success criteria"
    ]):
        category = "LOGIC_ERROR"
        guidance = {
            "stage": "Goal",
            "action": "Update goal definition",
            "files_to_edit": ["agent.py (goal section)"],
            "restart_required": True,
            "description": "Goal definition is wrong - update and rebuild"
        }

    elif any(pattern in failure_info["error_message"].lower() for pattern in [
        "timeout", "rate limit", "empty", "boundary", "edge case"
    ]):
        category = "EDGE_CASE"
        guidance = {
            "stage": "Eval",
            "action": "Add edge case test and fix handling",
            "files_to_edit": ["agent.py", "tests/test_edge_cases.py"],
            "restart_required": False,
            "description": "New scenario - add test and handle it"
        }

    else:
        category = "UNKNOWN"
        guidance = {
            "stage": "Unknown",
            "action": "Manual investigation required",
            "restart_required": False
        }

    return {
        "category": category,
        "guidance": guidance,
        "failure_info": failure_info
    }
```

**Show categorization to user:**

```python
AskUserQuestion(
    questions=[{
        "question": f"Test failed with {category}. How would you like to proceed?",
        "header": "Test Failure",
        "options": [
            {
                "label": "Fix code directly (Recommended)" if category == "IMPLEMENTATION_ERROR" else "Update goal",
                "description": guidance["description"]
            },
            {
                "label": "Show detailed error info",
                "description": "View full stack trace and logs"
            },
            {
                "label": "Skip for now",
                "description": "Continue with other tests"
            }
        ],
        "multiSelect": false
    }]
)
```

### Step 8: Iterate Based on Error Category

#### IMPLEMENTATION_ERROR → Fix Agent Code

```python
# 1. Show user the exact file and line that failed
print(f"Error in: exports/{agent_name}/nodes/__init__.py:42")
print(f"Issue: 'NoneType' object has no attribute 'get'")

# 2. Read the problematic code
code = Read(file_path=f"exports/{agent_name}/nodes/__init__.py")

# 3. User can fix directly, or you suggest a fix:
Edit(
    file_path=f"exports/{agent_name}/nodes/__init__.py",
    old_string="if results.get('videos'):",
    new_string="if results and results.get('videos'):"
)

# 4. Re-run tests immediately (instant feedback!)
Bash(
    command=f"cd /home/timothy/oss/hive && PYTHONPATH=core:exports:$PYTHONPATH pytest exports/{agent_name}/tests/ -v",
    description="Re-run tests after fix"
)
```

#### LOGIC_ERROR → Update Goal

```python
# 1. Show user the goal definition
goal_code = Read(file_path=f"exports/{agent_name}/agent.py")

# 2. Discuss what needs to change in success_criteria or constraints

# 3. Edit the goal
Edit(
    file_path=f"exports/{agent_name}/agent.py",
    old_string='target="3-5 videos"',
    new_string='target="1-5 videos"'  # More realistic
)

# 4. May need to regenerate agent nodes if goal changed significantly
# This requires going back to building-agents skill
```

#### EDGE_CASE → Add Test and Fix

```python
# 1. Create new edge case test with API key enforcement
edge_case_test = '''
@pytest.mark.asyncio
async def test_edge_case_empty_results(mock_mode):
    """Test: Agent handles no results gracefully"""
    result = await default_agent.run({{"query": "xyzabc123nonsense"}}, mock_mode=mock_mode)

    # Should succeed with empty results, not crash
    assert result.success or result.error is not None
    if result.success:
        assert result.output.get("message") == "No results found"
'''

# 2. Add to test file
Edit(
    file_path=f"exports/{agent_name}/tests/test_edge_cases.py",
    old_string="# Add edge case tests here",
    new_string=edge_case_test
)

# 3. Fix agent to handle edge case
# Edit agent code to handle empty results

# 4. Re-run tests
```

## Test File Templates

### Constraint Test Template

```python
"""Constraint tests for {agent_name}.

These tests validate that the agent respects its defined constraints.
Requires ANTHROPIC_API_KEY for real testing.
"""

import os
import pytest
from exports.{agent_name} import default_agent


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


@pytest.mark.asyncio
async def test_constraint_{constraint_id}():
    """Test: {constraint_description}"""
    # Test implementation based on constraint type
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({{"test": "input"}}, mock_mode=mock_mode)

    # Assert constraint is respected
    assert True  # Replace with actual check
```

### Success Criteria Test Template

```python
"""Success criteria tests for {agent_name}.

These tests validate that the agent achieves its defined success criteria.
Requires ANTHROPIC_API_KEY for real testing - mock mode cannot validate success criteria.
"""

import os
import pytest
from exports.{agent_name} import default_agent


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


@pytest.mark.asyncio
async def test_success_{criteria_id}():
    """Test: {criteria_description}"""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({{"test": "input"}}, mock_mode=mock_mode)

    assert result.success, f"Agent failed: {{result.error}}"

    # Verify success criterion met
    # e.g., assert metric meets target
    assert True  # Replace with actual check
```

### Edge Case Test Template

```python
"""Edge case tests for {agent_name}.

These tests validate agent behavior in unusual or boundary conditions.
Requires ANTHROPIC_API_KEY for real testing.
"""

import os
import pytest
from exports.{agent_name} import default_agent


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


@pytest.mark.asyncio
async def test_edge_case_{scenario_name}():
    """Test: Agent handles {scenario_description}"""
    mock_mode = bool(os.environ.get("MOCK_MODE"))
    result = await default_agent.run({{"edge": "case_input"}}, mock_mode=mock_mode)

    # Verify graceful handling
    assert result.success or result.error is not None
```

## Interactive Build + Test Loop

During agent construction (Agent stage), you can run constraint tests incrementally:

```python
# After adding first node
print("Added search_node. Running relevant constraint tests...")
Bash(
    command=f"pytest exports/{agent_name}/tests/test_constraints.py::test_constraint_api_rate_limits -v",
    description="Test API rate limits with current nodes"
)

# After adding second node
print("Added filter_node. Running all constraint tests...")
Bash(
    command=f"pytest exports/{agent_name}/tests/test_constraints.py -v",
    description="Run all constraint tests"
)
```

This provides **immediate feedback** during development, catching issues early.

## Common Test Patterns

**Note:** All test patterns should include API key enforcement via conftest.py.

### Happy Path Test
```python
@pytest.mark.asyncio
async def test_happy_path(mock_mode):
    """Test normal successful execution"""
    result = await default_agent.run({{"query": "python tutorials"}}, mock_mode=mock_mode)
    assert result.success
    assert len(result.output) > 0
```

### Boundary Condition Test
```python
@pytest.mark.asyncio
async def test_boundary_minimum(mock_mode):
    """Test at minimum threshold"""
    result = await default_agent.run({{"query": "very specific niche topic"}}, mock_mode=mock_mode)
    assert result.success
    assert len(result.output.get("results", [])) >= 1
```

### Error Handling Test
```python
@pytest.mark.asyncio
async def test_error_handling(mock_mode):
    """Test graceful error handling"""
    result = await default_agent.run({{"query": ""}}, mock_mode=mock_mode)  # Invalid input
    assert not result.success or result.output.get("error") is not None
```

### Performance Test
```python
@pytest.mark.asyncio
async def test_performance_latency(mock_mode):
    """Test response time is acceptable"""
    import time
    start = time.time()
    result = await default_agent.run({{"query": "test"}}, mock_mode=mock_mode)
    duration = time.time() - start
    assert duration < 5.0, f"Took {{duration}}s, expected <5s"
```

## Integration with building-agents

### Handoff Points

| Scenario | From | To | Action |
|----------|------|-----|--------|
| Agent built, ready to test | building-agents | testing-agent | Generate success tests |
| LOGIC_ERROR found | testing-agent | building-agents | Update goal, rebuild |
| IMPLEMENTATION_ERROR found | testing-agent | Direct fix | Edit agent files, re-run tests |
| EDGE_CASE found | testing-agent | testing-agent | Add edge case test |
| All tests pass | testing-agent | Done | Agent validated ✅ |

### Iteration Speed Comparison

| Scenario | Old Approach | New Approach |
|----------|--------------|--------------|
| **Bug Fix** | Rebuild via MCP tools (14 min) | Edit Python file, pytest (2 min) |
| **Add Test** | Generate via MCP, export (5 min) | Write test file directly (1 min) |
| **Debug** | Read subprocess logs | pdb, breakpoints, prints |
| **Inspect** | Limited visibility | Full Python introspection |

## Anti-Patterns

| Don't | Do Instead |
|-------|------------|
| ❌ Use MCP tools to generate tests | ✅ Write test files directly with Write/Edit |
| ❌ Store tests in session state | ✅ Write to tests/ directory immediately |
| ❌ Run tests via subprocess wrapper | ✅ Use pytest directly |
| ❌ Wait to "export" tests | ✅ Tests exist when generated |
| ❌ Hide test code from user | ✅ User sees and can edit all test files |
| ❌ Auto-approve generated tests | ✅ Always require user approval |
| ❌ Treat all failures the same | ✅ Categorize and iterate appropriately |
| ❌ Rebuild entire agent for small bugs | ✅ Edit code directly, re-run tests |
| ❌ Run tests without API key | ✅ Always set ANTHROPIC_API_KEY first |
| ❌ Use mock mode for real testing | ✅ Mock mode is ONLY for structure validation |
| ❌ Skip API key enforcement in tests | ✅ Include check_api_key fixture in conftest.py |

## Workflow Summary

```
1. Check existing tests (Glob)
   ↓
2. Generate test files (Write) → USER APPROVAL
   ↓
3. Run tests (pytest via Bash)
   ↓
4. Categorize failures
   ↓
5. Fix based on category:
   - IMPLEMENTATION_ERROR → Edit agent code
   - LOGIC_ERROR → Update goal
   - EDGE_CASE → Add test and fix
   ↓
6. Re-run tests (instant feedback)
   ↓
7. Repeat until all pass ✅
```

## Example Commands Reference

```bash
# FIRST: Set your API key (required for real testing)
export ANTHROPIC_API_KEY="your-key-here"

# Run all tests (with real LLM calls)
pytest exports/my_agent/tests/ -v

# Run specific test file
pytest exports/my_agent/tests/test_constraints.py -v

# Run specific test
pytest exports/my_agent/tests/test_success_criteria.py::test_success_find_results -v

# Run with debugging on first failure
pytest exports/my_agent/tests/ -v --pdb

# Run in parallel (faster)
pytest exports/my_agent/tests/ -n 4

# Run with coverage report
pytest exports/my_agent/tests/ --cov=exports/my_agent --cov-report=html

# Run only failed tests from last run
pytest exports/my_agent/tests/ --lf

# Run tests matching pattern
pytest exports/my_agent/tests/ -k "constraint" -v

# Mock mode (structure validation only - NOT for real testing)
MOCK_MODE=1 pytest exports/my_agent/tests/ -v
```

---

**The new testing approach gives you direct Python access, instant feedback, and 10x faster iteration! 🚀**
