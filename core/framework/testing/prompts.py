"""
LLM prompt templates for test generation.

These prompts instruct the LLM to generate pytest-compatible tests
from Goal success_criteria and constraints using tool calling.
"""

CONSTRAINT_TEST_PROMPT = """You are generating test cases for an AI agent's constraints.

## Goal
Name: {goal_name}
Description: {goal_description}

## Constraints to Test
{constraints_formatted}

## Instructions
For each constraint, generate pytest-compatible tests that verify the constraint is satisfied.

For EACH test, call the `submit_test` tool with:
- constraint_id: The ID of the constraint being tested
- test_name: A descriptive pytest function name (test_constraint_<constraint_id>_<scenario>)
- test_code: Complete Python test function code
- description: What the test validates
- input: Test input data as an object
- expected_output: Expected output as an object
- confidence: 0-1 score based on how testable/well-defined the constraint is

Consider for each constraint:
- Happy path: Normal execution that should satisfy the constraint
- Boundary conditions: Inputs at the edge of constraint boundaries
- Violation scenarios: Inputs that should trigger constraint violation

The test code should:
- Be valid Python using pytest conventions
- Use `agent.run(input)` to execute the agent
- Include descriptive assertion messages
- Handle potential exceptions appropriately

Generate tests now by calling submit_test for each test."""

SUCCESS_CRITERIA_TEST_PROMPT = """You are generating success criteria tests for an AI agent.

## Goal
Name: {goal_name}
Description: {goal_description}

## Success Criteria
{success_criteria_formatted}

## Agent Flow (for context)
Nodes: {node_names}
Tools: {tool_names}

## Instructions
For each success criterion, generate tests that verify the agent achieves its goals.

For EACH test, call the `submit_test` tool with:
- criteria_id: The ID of the success criterion being tested
- test_name: A descriptive pytest function name (test_<criteria_id>_<scenario>)
- test_code: Complete Python test function code
- description: What the test validates
- input: Test input data as an object
- expected_output: Expected output as an object
- confidence: 0-1 score based on how measurable/specific the criterion is

Consider for each criterion:
- Happy path: Normal successful execution
- Boundary conditions: Exactly at target thresholds (if applicable)
- Graceful handling: Near-misses and edge cases

The test code should:
- Be valid Python using pytest conventions
- Use `agent.run(input)` to execute the agent
- Validate the metric defined in the success criterion
- Include descriptive assertion messages

Generate tests now by calling submit_test for each test."""

EDGE_CASE_TEST_PROMPT = """You are generating edge case tests for an AI agent.

## Goal
Name: {goal_name}
Description: {goal_description}

## Existing Tests
{existing_tests_summary}

## Recent Failures (if any)
{failures_summary}

## Instructions
Generate additional edge case tests that cover scenarios not addressed by existing tests.

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
- test_code: Complete Python test function code
- description: What the test validates
- input: Test input data as an object
- expected_output: Expected output as an object
- confidence: 0-1 score

Generate edge case tests now by calling submit_test for each test."""
