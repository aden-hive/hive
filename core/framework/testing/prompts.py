"""
LLM prompt templates for test generation.

These prompts instruct the LLM to generate pytest-compatible async tests
from Goal success_criteria and constraints using tool calling.

Tests are written to exports/{agent}/tests/ as Python files and run with pytest.
"""

# Template for the test file header (imports and fixtures)
PYTEST_TEST_FILE_HEADER = '''"""
{test_type} tests for {agent_name}.

{description}

REQUIRES: ANTHROPIC_API_KEY for real testing.
"""

import os
import pytest
from exports.{agent_module} import default_agent


def _get_api_key():
    """Get API key from CredentialManager or environment."""
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        if creds.is_available("anthropic"):
            return creds.get("anthropic")
    except ImportError:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


# Skip all tests if no API key and not in mock mode
pytestmark = pytest.mark.skipif(
    not _get_api_key() and not os.environ.get("MOCK_MODE"),
    reason="API key required. Set ANTHROPIC_API_KEY or use MOCK_MODE=1."
)


'''

# Template for conftest.py with shared fixtures
PYTEST_CONFTEST_TEMPLATE = '''"""Shared test fixtures for {agent_name} tests."""

import os
import pytest


def _get_api_key():
    """Get API key from CredentialManager or environment."""
    try:
        from aden_tools.credentials import CredentialManager
        creds = CredentialManager()
        if creds.is_available("anthropic"):
            return creds.get("anthropic")
    except ImportError:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


@pytest.fixture
def mock_mode():
    """Check if running in mock mode."""
    return bool(os.environ.get("MOCK_MODE"))


@pytest.fixture(scope="session", autouse=True)
def check_api_key():
    """Ensure API key is set for real testing."""
    if not _get_api_key():
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
'''


CONSTRAINT_TEST_PROMPT = """You are generating pytest-compatible async test cases for an AI agent's constraints.

## Goal
Name: {goal_name}
Description: {goal_description}

## Agent Module
Import path: {agent_module}

## Constraints to Test
{constraints_formatted}

## Instructions
For each constraint, generate pytest-compatible ASYNC tests that verify the constraint is satisfied.

For EACH test, call the `submit_test` tool with:
- constraint_id: The ID of the constraint being tested
- test_name: A descriptive pytest function name (test_constraint_<constraint_id>_<scenario>)
- test_code: Complete Python async test function code (see format below)
- description: What the test validates
- input: Test input data as an object
- expected_output: Expected output as an object
- confidence: 0-1 score based on how testable/well-defined the constraint is

Consider for each constraint:
- Happy path: Normal execution that should satisfy the constraint
- Boundary conditions: Inputs at the edge of constraint boundaries
- Violation scenarios: Inputs that should trigger constraint violation

## REQUIRED Test Code Format

The test code MUST follow this exact format:

```python
@pytest.mark.asyncio
async def test_constraint_<constraint_id>_<scenario>(mock_mode):
    \"\"\"Test: <description>\"\"\"
    result = await default_agent.run({{"key": "value"}}, mock_mode=mock_mode)

    # Assertions with descriptive messages
    assert condition, "Error message explaining what failed"
```

IMPORTANT:
- Every test function MUST be async with @pytest.mark.asyncio decorator
- Every test MUST accept `mock_mode` as a parameter
- Use `await default_agent.run(input, mock_mode=mock_mode)` to execute the agent
- `default_agent` is already imported - do NOT add import statements
- Do NOT include any imports in test_code - they're in the file header

Generate tests now by calling submit_test for each test."""

SUCCESS_CRITERIA_TEST_PROMPT = """You are generating pytest-compatible async success criteria tests for an AI agent.

## Goal
Name: {goal_name}
Description: {goal_description}

## Agent Module
Import path: {agent_module}

## Success Criteria
{success_criteria_formatted}

## Agent Flow (for context)
Nodes: {node_names}
Tools: {tool_names}

## Instructions
For each success criterion, generate pytest-compatible ASYNC tests that verify the agent achieves its goals.

For EACH test, call the `submit_test` tool with:
- criteria_id: The ID of the success criterion being tested
- test_name: A descriptive pytest function name (test_success_<criteria_id>_<scenario>)
- test_code: Complete Python async test function code (see format below)
- description: What the test validates
- input: Test input data as an object
- expected_output: Expected output as an object
- confidence: 0-1 score based on how measurable/specific the criterion is

Consider for each criterion:
- Happy path: Normal successful execution
- Boundary conditions: Exactly at target thresholds (if applicable)
- Graceful handling: Near-misses and edge cases

## REQUIRED Test Code Format

The test code MUST follow this exact format:

```python
@pytest.mark.asyncio
async def test_success_<criteria_id>_<scenario>(mock_mode):
    \"\"\"Test: <description>\"\"\"
    result = await default_agent.run({{"key": "value"}}, mock_mode=mock_mode)

    assert result.success, f"Agent failed: {{result.error}}"
    # Additional assertions with descriptive messages
    assert condition, "Error message explaining what failed"
```

IMPORTANT:
- Every test function MUST be async with @pytest.mark.asyncio decorator
- Every test MUST accept `mock_mode` as a parameter
- Use `await default_agent.run(input, mock_mode=mock_mode)` to execute the agent
- `default_agent` is already imported - do NOT add import statements
- Do NOT include any imports in test_code - they're in the file header

Generate tests now by calling submit_test for each test."""

EDGE_CASE_TEST_PROMPT = """You are generating pytest-compatible async edge case tests for an AI agent.

## Goal
Name: {goal_name}
Description: {goal_description}

## Agent Module
Import path: {agent_module}

## Existing Tests
{existing_tests_summary}

## Recent Failures (if any)
{failures_summary}

## Instructions
Generate additional pytest-compatible ASYNC edge case tests that cover scenarios not addressed by existing tests.

Focus on:
1. Unusual input formats or values
2. Empty or null inputs
3. Extremely large or small values
4. Unicode and special characters
5. Concurrent or timing-related scenarios
6. Network/API failure simulations (if applicable)

For EACH test, call the `submit_test` tool with:
- criteria_id: An identifier for the edge case category being tested
- test_name: A descriptive pytest function name (test_edge_case_<scenario>)
- test_code: Complete Python async test function code (see format below)
- description: What the test validates
- input: Test input data as an object
- expected_output: Expected output as an object
- confidence: 0-1 score

## REQUIRED Test Code Format

The test code MUST follow this exact format:

```python
@pytest.mark.asyncio
async def test_edge_case_<scenario>(mock_mode):
    \"\"\"Test: <description>\"\"\"
    result = await default_agent.run({{"edge": "case_input"}}, mock_mode=mock_mode)

    # Verify graceful handling
    assert result.success or result.error is not None, "Should handle edge case gracefully"
```

IMPORTANT:
- Every test function MUST be async with @pytest.mark.asyncio decorator
- Every test MUST accept `mock_mode` as a parameter
- Use `await default_agent.run(input, mock_mode=mock_mode)` to execute the agent
- `default_agent` is already imported - do NOT add import statements
- Do NOT include any imports in test_code - they're in the file header

Generate edge case tests now by calling submit_test for each test."""
