"""
Constraint test generator.

Generates tests for Goal constraints using LLM.
Tests are returned with PENDING approval status.
"""

import uuid
from typing import TYPE_CHECKING

from framework.graph.goal import Goal, Constraint
from framework.testing.test_case import Test, TestType, ApprovalStatus
from framework.testing.prompts import CONSTRAINT_TEST_PROMPT
from framework.llm.provider import Tool, ToolUse, ToolResult

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider


# Tool for collecting generated tests - Claude handles JSON escaping automatically
SUBMIT_TEST_TOOL = Tool(
    name="submit_test",
    description="Submit a generated constraint test. Call once per test.",
    parameters={
        "properties": {
            "constraint_id": {
                "type": "string",
                "description": "ID of the constraint being tested",
            },
            "test_name": {
                "type": "string",
                "description": "pytest function name, e.g., test_constraint_api_limits_respected",
            },
            "test_code": {
                "type": "string",
                "description": "Complete Python test function code",
            },
            "description": {
                "type": "string",
                "description": "What the test validates",
            },
            "input": {
                "type": "object",
                "description": "Test input data",
            },
            "expected_output": {
                "type": "object",
                "description": "Expected output",
            },
            "confidence": {
                "type": "number",
                "description": "Confidence score 0-1",
            },
        },
        "required": ["constraint_id", "test_name", "test_code", "description", "confidence"],
    },
)


class ConstraintTestGenerator:
    """
    Generate constraint tests from Goal constraints.

    Generated tests require user approval before being added to the test suite.
    """

    def __init__(self, llm: "LLMProvider"):
        """
        Initialize generator with LLM provider.

        Args:
            llm: LLM provider for test generation (e.g., AnthropicProvider)
        """
        self.llm = llm

    def generate(self, goal: Goal) -> list[Test]:
        """
        Generate tests for all constraints in a goal.

        Args:
            goal: Goal with constraints to test

        Returns:
            List of Test objects with approval_status=PENDING.
            These MUST be approved before being added to the test suite.
        """
        if not goal.constraints:
            return []

        # Format prompt
        prompt = CONSTRAINT_TEST_PROMPT.format(
            goal_name=goal.name,
            goal_description=goal.description,
            constraints_formatted=self._format_constraints(goal.constraints),
        )

        # Collect tests via tool calls - Claude handles JSON escaping automatically
        collected_tests: list[dict] = []

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            if tool_use.name == "submit_test":
                collected_tests.append(tool_use.input)
                return ToolResult(
                    tool_use_id=tool_use.id, content="Test recorded successfully"
                )
            return ToolResult(
                tool_use_id=tool_use.id, content="Unknown tool", is_error=True
            )

        self.llm.complete_with_tools(
            messages=[{"role": "user", "content": prompt}],
            system="You are a test generation expert. For each constraint, call the submit_test tool with the test details.",
            tools=[SUBMIT_TEST_TOOL],
            tool_executor=tool_executor,
            max_iterations=20,
        )

        return self._create_tests_from_collected(collected_tests, goal.id)

    def generate_for_constraint(
        self, goal: Goal, constraint: Constraint
    ) -> list[Test]:
        """
        Generate tests for a single constraint.

        Args:
            goal: Goal containing the constraint
            constraint: Specific constraint to test

        Returns:
            List of Test objects for the constraint
        """
        # Format prompt with just this constraint
        prompt = CONSTRAINT_TEST_PROMPT.format(
            goal_name=goal.name,
            goal_description=goal.description,
            constraints_formatted=self._format_constraint(constraint),
        )

        # Collect tests via tool calls
        collected_tests: list[dict] = []

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            if tool_use.name == "submit_test":
                collected_tests.append(tool_use.input)
                return ToolResult(
                    tool_use_id=tool_use.id, content="Test recorded successfully"
                )
            return ToolResult(
                tool_use_id=tool_use.id, content="Unknown tool", is_error=True
            )

        self.llm.complete_with_tools(
            messages=[{"role": "user", "content": prompt}],
            system="You are a test generation expert. Call the submit_test tool with the test details.",
            tools=[SUBMIT_TEST_TOOL],
            tool_executor=tool_executor,
            max_iterations=10,
        )

        return self._create_tests_from_collected(collected_tests, goal.id)

    def _format_constraints(self, constraints: list[Constraint]) -> str:
        """Format constraints for prompt."""
        lines = []
        for c in constraints:
            lines.append(self._format_constraint(c))
            lines.append("")
        return "\n".join(lines)

    def _format_constraint(self, constraint: Constraint) -> str:
        """Format a single constraint for prompt."""
        severity = "HARD" if constraint.constraint_type == "hard" else "SOFT"
        return f"""### Constraint: {constraint.id}
- Type: {severity} ({constraint.constraint_type})
- Category: {constraint.category}
- Description: {constraint.description}
- Check: {constraint.check}"""

    def _create_tests_from_collected(
        self, collected: list[dict], goal_id: str
    ) -> list[Test]:
        """Create Test objects from tool call data."""
        tests = []
        for td in collected:
            test = Test(
                id=f"test_{uuid.uuid4().hex[:8]}",
                goal_id=goal_id,
                parent_criteria_id=td.get("constraint_id", "unknown"),
                test_type=TestType.CONSTRAINT,
                test_name=td.get("test_name", "unnamed_test"),
                test_code=td.get("test_code", ""),
                description=td.get("description", ""),
                input=td.get("input", {}),
                expected_output=td.get("expected_output", {}),
                generated_by="llm",
                llm_confidence=float(td.get("confidence", 0.5)),
                approval_status=ApprovalStatus.PENDING,
            )
            tests.append(test)
        return tests
