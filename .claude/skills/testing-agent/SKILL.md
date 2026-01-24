---
name: testing-agent
description: Run goal-based evaluation tests for agents. Use when you need to verify an agent meets its goals, debug failing tests, or iterate on agent improvements based on test results.
---

# Testing Workflow

This skill provides tools for testing agents built with the building-agents skill.

## Workflow Overview

1. `mcp__agent-builder__list_tests` - Check what tests exist
2. `mcp__agent-builder__generate_constraint_tests` or `mcp__agent-builder__generate_success_tests` - Get test guidelines
3. **Write tests directly** using the Write tool with the guidelines provided
4. `mcp__agent-builder__run_tests` - Execute tests
5. `mcp__agent-builder__debug_test` - Debug failures

## How Test Generation Works

The `generate_*_tests` MCP tools return **guidelines and templates** - they do NOT generate test code via LLM.
You (Claude) write the tests directly using the Write tool based on the guidelines.

### Example Workflow

```python
# Step 1: Get test guidelines
result = mcp__agent-builder__generate_constraint_tests(
    goal_id="my-goal",
    goal_json='{"id": "...", "constraints": [...]}',
    agent_path="exports/my_agent"
)

# Step 2: The result contains:
# - output_file: where to write tests
# - file_header: imports and fixtures to use
# - test_template: format for test functions
# - constraints_formatted: the constraints to test
# - test_guidelines: rules for writing tests

# Step 3: Write tests directly using the Write tool
Write(
    file_path=result["output_file"],
    content=result["file_header"] + test_code_you_write
)

# Step 4: Run tests via MCP tool
mcp__agent-builder__run_tests(
    goal_id="my-goal",
    agent_path="exports/my_agent"
)

# Step 5: Debug failures via MCP tool
mcp__agent-builder__debug_test(
    goal_id="my-goal",
    test_name="test_constraint_foo",
    agent_path="exports/my_agent"
)
```

---

# Testing Agents with MCP Tools

Run goal-based evaluation tests for agents built with the building-agents skill.

**Key Principle: MCP tools provide guidelines, Claude writes tests directly**
- ✅ Get guidelines: `generate_constraint_tests`, `generate_success_tests` → returns templates and guidelines
- ✅ Write tests: Use the Write tool with the provided file_header and test_template
- ✅ Run tests: `run_tests` (runs pytest via subprocess)
- ✅ Debug failures: `debug_test` (re-runs single test with verbose output)
- ✅ List tests: `list_tests` (scans Python test files)
- ✅ Tests stored in `exports/{agent}/tests/test_*.py`

## Architecture: Python Test Files

```
exports/my_agent/
├── __init__.py
├── agent.py              ← Agent to test
├── nodes/__init__.py
├── config.py
├── __main__.py
└── tests/                ← Test files written by MCP tools
    ├── conftest.py       # Shared fixtures (auto-created)
    ├── test_constraints.py
    ├── test_success_criteria.py
    └── test_edge_cases.py
```

**Tests import the agent directly:**
```python
import pytest
from exports.my_agent import default_agent


@pytest.mark.asyncio
async def test_happy_path(mock_mode):
    result = await default_agent.run({"query": "test"}, mock_mode=mock_mode)
    assert result.success
    assert len(result.output) > 0
```

## Why This Approach

- MCP tools provide consistent test guidelines with proper imports, fixtures, and API key enforcement
- Claude writes tests directly, eliminating circular LLM dependencies in the MCP server
- `run_tests` parses pytest output into structured results for iteration
- `debug_test` provides formatted output with actionable debugging info
- File headers include conftest.py setup with proper fixtures

## Quick Start

1. **Check existing tests** - `list_tests(goal_id, agent_path)`
2. **Get test guidelines** - `generate_constraint_tests` or `generate_success_tests`
3. **Write tests** - Use the Write tool with the provided file_header and guidelines
4. **Run tests** - `run_tests(goal_id, agent_path)`
5. **Debug failures** - `debug_test(goal_id, test_name, agent_path)`
6. **Iterate** - Repeat steps 4-5 until all pass

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
from aden_tools.credentials import CredentialManager

# At the top of every test file
pytestmark = pytest.mark.skipif(
    not CredentialManager().is_available("anthropic") and not os.environ.get("MOCK_MODE"),
    reason="API key required for real testing. Set ANTHROPIC_API_KEY or use MOCK_MODE=1 for structure validation only."
)


@pytest.fixture(scope="session", autouse=True)
def check_api_key():
    """Ensure API key is set for real testing."""
    creds = CredentialManager()
    if not creds.is_available("anthropic"):
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
from aden_tools.credentials import CredentialManager

# Before running any tests
creds = CredentialManager()
if not creds.is_available("anthropic"):
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
│    run_tests(goal_id, agent_path, test_types='["constraint"]')          │
└─────────────────────────────────────────────────────────────────────────┘
                                   ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                           EVAL STAGE (this skill)                        │
│                                                                          │
│  1. Generate SUCCESS_CRITERIA TESTS → Write to tests/ → USER APPROVAL   │
│     Files created: exports/{agent}/tests/test_success_criteria.py       │
│  2. Run all tests: run_tests(goal_id, agent_path)                       │
│  3. On failure → debug_test(goal_id, test_name, agent_path)             │
│  4. Iterate: Edit agent code → Re-run run_tests (instant feedback)      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Step-by-Step: Testing an Agent

### Step 1: Check Existing Tests

**ALWAYS check first** before generating new tests:

```python
mcp__agent-builder__list_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent"
)
```

This shows what test files already exist. If tests exist:
- Review the list to see what's covered
- Ask user if they want to add more or run existing tests

### Step 2: Get Constraint Test Guidelines (Goal Stage)

After goal is defined, get test guidelines using the MCP tool:

```python
# First, read the goal from agent.py to get the goal JSON
goal_code = Read(file_path="exports/your_agent/agent.py")
# Extract the goal definition and convert to JSON

# Get constraint test guidelines via MCP tool
result = mcp__agent-builder__generate_constraint_tests(
    goal_id="your-goal-id",
    goal_json='{"id": "goal-id", "name": "...", "constraints": [...]}',
    agent_path="exports/your_agent"
)
```

**Response includes:**
- `output_file`: Where to write tests (e.g., `exports/your_agent/tests/test_constraints.py`)
- `file_header`: Imports, fixtures, and pytest setup to use at the top of the file
- `test_template`: Format for test functions
- `constraints_formatted`: The constraints to test
- `test_guidelines`: Rules and best practices for writing tests
- `instruction`: How to proceed

**Write tests directly** using the provided guidelines:

```python
# Write tests using the Write tool
Write(
    file_path=result["output_file"],
    content=result["file_header"] + "\n\n" + your_test_code
)
```

### Step 3: Get Success Criteria Test Guidelines (Eval Stage)

After agent is fully built, get success criteria test guidelines:

```python
# Get success criteria test guidelines via MCP tool
result = mcp__agent-builder__generate_success_tests(
    goal_id="your-goal-id",
    goal_json='{"id": "goal-id", "name": "...", "success_criteria": [...]}',
    node_names="analyze_request,search_web,format_results",
    tool_names="web_search,web_scrape",
    agent_path="exports/your_agent"
)
```

**Write tests directly** using the provided guidelines:

```python
# Write tests using the Write tool
Write(
    file_path=result["output_file"],
    content=result["file_header"] + "\n\n" + your_test_code
)
```

### Step 4: Test Fixtures (conftest.py)

The `file_header` returned by the MCP tools includes proper imports and fixtures.
You should also create a conftest.py file in the tests directory with shared fixtures:

```python
# Create conftest.py with the conftest template
Write(
    file_path="exports/your_agent/tests/conftest.py",
    content=conftest_content  # Use PYTEST_CONFTEST_TEMPLATE format
)
```

### Step 5: Run Tests

**Use the MCP tool to run tests** (not pytest directly):

```python
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent"
)

**Response includes structured results:**
```json
{
  "goal_id": "your-goal-id",
  "overall_passed": false,
  "summary": {
    "total": 12,
    "passed": 10,
    "failed": 2,
    "skipped": 0,
    "errors": 0,
    "pass_rate": "83.3%"
  },
  "test_results": [
    {"file": "test_constraints.py", "test_name": "test_constraint_api_rate_limits", "status": "passed"},
    {"file": "test_success_criteria.py", "test_name": "test_success_find_relevant_results", "status": "failed"}
  ],
  "failures": [
    {"test_name": "test_success_find_relevant_results", "details": "AssertionError: Expected 3-5 results..."}
  ]
}
```

**Options for `run_tests`:**
```python
# Run only constraint tests
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    test_types='["constraint"]'
)

# Run with parallel workers
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    parallel=4
)

# Stop on first failure
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    fail_fast=True
)
```

### Step 6: Debug Failed Tests

**Use the MCP tool to debug** (not Bash/pytest directly):

```python
mcp__agent-builder__debug_test(
    goal_id="your-goal-id",
    test_name="test_success_find_relevant_results",
    agent_path="exports/your_agent"
)
```

**Response includes:**
- Full verbose output from the test
- Stack trace with exact line numbers
- Captured logs and prints
- Suggestions for fixing the issue

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
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path=f"exports/{agent_name}"
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

## Test File Templates (Reference Only)

**⚠️ Do NOT copy-paste these templates directly.** Use `generate_constraint_tests` and `generate_success_tests` MCP tools to create properly structured tests with correct imports and fixtures.

These templates show the structure of generated tests for reference only.

### Constraint Test Template

```python
"""Constraint tests for {agent_name}.

These tests validate that the agent respects its defined constraints.
Requires ANTHROPIC_API_KEY for real testing.
"""

import os
import pytest
from exports.{agent_name} import default_agent
from aden_tools.credentials import CredentialManager


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not CredentialManager().is_available("anthropic") and not os.environ.get("MOCK_MODE"),
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
from aden_tools.credentials import CredentialManager


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not CredentialManager().is_available("anthropic") and not os.environ.get("MOCK_MODE"),
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
from aden_tools.credentials import CredentialManager


# Enforce API key for real testing
pytestmark = pytest.mark.skipif(
    not CredentialManager().is_available("anthropic") and not os.environ.get("MOCK_MODE"),
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
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path=f"exports/{agent_name}",
    test_types='["constraint"]'
)

# After adding second node
print("Added filter_node. Running all constraint tests...")
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path=f"exports/{agent_name}",
    test_types='["constraint"]'
)
```

This provides **immediate feedback** during development, catching issues early.

## Common Test Patterns

**Note:** All test patterns should include API key enforcement via conftest.py.

### ⚠️ CRITICAL: Framework Features You Must Know

#### OutputCleaner - Automatic I/O Cleaning (NEW!)

**The framework now automatically validates and cleans node outputs** using a fast LLM (Cerebras llama-3.3-70b) at edge traversal time. This prevents cascading failures from malformed output.

**What OutputCleaner does**:
- ✅ Validates output matches next node's input schema
- ✅ Detects JSON parsing trap (entire response in one key)
- ✅ Cleans malformed output automatically (~200-500ms, ~$0.001 per cleaning)
- ✅ Boosts success rates by 1.8-2.2x

**Impact on tests**: Tests should still use safe patterns because OutputCleaner may not catch all issues in test mode.

#### Safe Test Patterns (REQUIRED)

**❌ UNSAFE** (will cause test failures):
```python
# Direct key access - can crash!
approval_decision = result.output["approval_decision"]
assert approval_decision == "APPROVED"

# Nested access without checks
category = result.output["analysis"]["category"]

# Assuming parsed JSON structure
for issue in result.output["compliance_issues"]:
    ...
```

**✅ SAFE** (correct patterns):
```python
# 1. Safe dict access with .get()
output = result.output or {}
approval_decision = output.get("approval_decision", "UNKNOWN")
assert "APPROVED" in approval_decision or approval_decision == "APPROVED"

# 2. Type checking before operations
analysis = output.get("analysis", {})
if isinstance(analysis, dict):
    category = analysis.get("category", "unknown")

# 3. Parse JSON from strings (the JSON parsing trap!)
import json
recommendation = output.get("recommendation", "{}")
if isinstance(recommendation, str):
    try:
        parsed = json.loads(recommendation)
        if isinstance(parsed, dict):
            approval = parsed.get("approval_decision", "UNKNOWN")
    except json.JSONDecodeError:
        approval = "UNKNOWN"
elif isinstance(recommendation, dict):
    approval = recommendation.get("approval_decision", "UNKNOWN")

# 4. Safe iteration with type check
compliance_issues = output.get("compliance_issues", [])
if isinstance(compliance_issues, list):
    for issue in compliance_issues:
        ...
```

#### Helper Functions for Safe Access

**Add to conftest.py**:
```python
import json
import re

def _parse_json_from_output(result, key):
    """Parse JSON from agent output (framework may store full LLM response as string)."""
    response_text = result.output.get(key, "")
    # Remove markdown code blocks if present
    json_text = re.sub(r'```json\s*|\s*```', '', response_text).strip()

    try:
        return json.loads(json_text)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return result.output.get(key)

def safe_get_nested(result, key_path, default=None):
    """Safely get nested value from result.output."""
    output = result.output or {}
    current = output

    for key in key_path:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, str):
            try:
                json_text = re.sub(r'```json\s*|\s*```', '', current).strip()
                parsed = json.loads(json_text)
                if isinstance(parsed, dict):
                    current = parsed.get(key)
                else:
                    return default
            except json.JSONDecodeError:
                return default
        else:
            return default

    return current if current is not None else default

# Make available in tests
pytest.parse_json_from_output = _parse_json_from_output
pytest.safe_get_nested = safe_get_nested
```

**Usage in tests**:
```python
# Use helper to parse JSON safely
parsed = pytest.parse_json_from_output(result, "recommendation")
if isinstance(parsed, dict):
    approval = parsed.get("approval_decision", "UNKNOWN")

# Safe nested access
risk_score = pytest.safe_get_nested(result, ["analysis", "risk_score"], default=0.0)
```

#### Test Count Guidance

**Generate 8-15 tests total, NOT 30+**

- ✅ 2-3 tests per success criterion
- ✅ 1 happy path test
- ✅ 1 boundary/edge case test
- ✅ 1 error handling test (optional)

**Why fewer tests?**:
- Each test requires real LLM call (~3 seconds, costs money)
- 30 tests = 90 seconds, $0.30+ in costs
- 12 tests = 36 seconds, $0.12 in costs
- Focus on quality over quantity

#### ExecutionResult Fields (Important!)

**`result.success=True` means NO exception, NOT goal achieved**

```python
# ❌ WRONG - assumes goal achieved
assert result.success

# ✅ RIGHT - check success AND output
assert result.success, f"Agent failed: {result.error}"
output = result.output or {}
approval = output.get("approval_decision")
assert approval == "APPROVED", f"Expected APPROVED, got {approval}"
```

**All ExecutionResult fields**:
- `success: bool` - Execution completed without exception (NOT goal achieved!)
- `output: dict` - Complete memory snapshot (may contain raw strings)
- `error: str | None` - Error message if failed
- `steps_executed: int` - Number of nodes executed
- `total_tokens: int` - Cumulative token usage
- `total_latency_ms: int` - Total execution time
- `path: list[str]` - Node IDs traversed
- `paused_at: str | None` - Node ID if HITL pause occurred
- `session_state: dict` - State for resuming

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

### Testing Best Practices

| Don't | Do Instead |
|-------|------------|
| ❌ Write tests without getting guidelines first | ✅ Use `generate_*_tests` to get proper file_header and guidelines |
| ❌ Run pytest via Bash | ✅ Use `run_tests` MCP tool for structured results |
| ❌ Debug tests with Bash pytest -vvs | ✅ Use `debug_test` MCP tool for formatted output |
| ❌ Check for tests with Glob | ✅ Use `list_tests` MCP tool |
| ❌ Skip the file_header from guidelines | ✅ Always include the file_header for proper imports and fixtures |

### General Testing

| Don't | Do Instead |
|-------|------------|
| ❌ Treat all failures the same | ✅ Use debug_test to categorize and iterate appropriately |
| ❌ Rebuild entire agent for small bugs | ✅ Edit code directly, re-run tests |
| ❌ Run tests without API key | ✅ Always set ANTHROPIC_API_KEY first |
| ❌ Write tests without understanding the constraints/criteria | ✅ Read the formatted constraints/criteria from guidelines |

## Workflow Summary

```
1. Check existing tests: list_tests(goal_id, agent_path)
   → Scans exports/{agent}/tests/test_*.py
   ↓
2. Get test guidelines: generate_constraint_tests, generate_success_tests
   → Returns file_header, test_template, constraints/criteria, guidelines
   ↓
3. Write tests: Use Write tool with the provided guidelines
   → Write tests to exports/{agent}/tests/test_*.py
   ↓
4. Run tests: run_tests(goal_id, agent_path)
   → Executes: pytest exports/{agent}/tests/ -v
   ↓
5. Debug failures: debug_test(goal_id, test_name, agent_path)
   → Re-runs single test with verbose output
   ↓
6. Fix based on category:
   - IMPLEMENTATION_ERROR → Edit agent code directly
   - ASSERTION_FAILURE → Fix agent logic or update test
   - IMPORT_ERROR → Check package structure
   - API_ERROR → Check API keys and connectivity
   ↓
7. Re-run tests: run_tests(goal_id, agent_path)
   ↓
8. Repeat until all pass ✅
```

## MCP Tools Reference

```python
# Check existing tests (scans Python test files)
mcp__agent-builder__list_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent"
)

# Get constraint test guidelines (returns templates and guidelines, NOT generated tests)
mcp__agent-builder__generate_constraint_tests(
    goal_id="your-goal-id",
    goal_json='{"id": "...", "constraints": [...]}',
    agent_path="exports/your_agent"
)
# Returns: output_file, file_header, test_template, constraints_formatted, test_guidelines

# Get success criteria test guidelines
mcp__agent-builder__generate_success_tests(
    goal_id="your-goal-id",
    goal_json='{"id": "...", "success_criteria": [...]}',
    node_names="node1,node2",
    tool_names="tool1,tool2",
    agent_path="exports/your_agent"
)
# Returns: output_file, file_header, test_template, success_criteria_formatted, test_guidelines

# Run tests via pytest subprocess
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent"
)

# Debug a failed test (re-runs with verbose output)
mcp__agent-builder__debug_test(
    goal_id="your-goal-id",
    test_name="test_constraint_foo",
    agent_path="exports/your_agent"
)
```

## run_tests Options

```python
# Run only constraint tests
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    test_types='["constraint"]'
)

# Run only success criteria tests
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    test_types='["success"]'
)

# Run with pytest-xdist parallelism (requires pytest-xdist)
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    parallel=4
)

# Stop on first failure
mcp__agent-builder__run_tests(
    goal_id="your-goal-id",
    agent_path="exports/your_agent",
    fail_fast=True
)
```

## Direct pytest Commands

You can also run tests directly with pytest (the MCP tools use pytest internally):

```bash
# Run all tests
pytest exports/your_agent/tests/ -v

# Run specific test file
pytest exports/your_agent/tests/test_constraints.py -v

# Run specific test
pytest exports/your_agent/tests/test_constraints.py::test_constraint_foo -vvs

# Run in mock mode (structure validation only)
MOCK_MODE=1 pytest exports/your_agent/tests/ -v
```

---

**MCP tools generate tests, write them to Python files, and run them via pytest.**
