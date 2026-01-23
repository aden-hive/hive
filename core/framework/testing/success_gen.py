"""
Success criteria test generator.

Generates tests for Goal success_criteria using LLM.
Tests are returned with PENDING approval status.
"""

import uuid
from typing import TYPE_CHECKING

from framework.graph.goal import Goal, SuccessCriterion
from framework.testing.test_case import Test, TestType, ApprovalStatus
from framework.testing.prompts import SUCCESS_CRITERIA_TEST_PROMPT
from framework.llm.provider import Tool, ToolUse, ToolResult

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider


# Tool for collecting generated tests - Claude handles JSON escaping automatically
SUBMIT_TEST_TOOL = Tool(
    name="submit_test",
    description="Submit a generated success criteria test. Call once per test.",
    parameters={
        "properties": {
            "criteria_id": {
                "type": "string",
                "description": "ID of the success criterion being tested",
            },
            "test_name": {
                "type": "string",
                "description": "pytest function name, e.g., test_find_videos_happy_path",
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
        "required": ["criteria_id", "test_name", "test_code", "description", "confidence"],
    },
)


class SuccessCriteriaTestGenerator:
    """
    Generate success criteria tests from Goal success_criteria.

    Generated tests require user approval before being added to the test suite.
    Unlike constraint tests, success criteria tests are generated during the
    Eval stage (after the agent exists) and may reference agent nodes/tools.
    """

    def __init__(self, llm: "LLMProvider"):
        """
        Initialize generator with LLM provider.

        Args:
            llm: LLM provider for test generation (e.g., AnthropicProvider)
        """
        self.llm = llm

    def generate(
        self,
        goal: Goal,
        node_names: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> list[Test]:
        """
        Generate tests for all success criteria in a goal.

        Args:
            goal: Goal with success_criteria to test
            node_names: Names of agent nodes (for context)
            tool_names: Names of tools available to agent (for context)

        Returns:
            List of Test objects with approval_status=PENDING.
            These MUST be approved before being added to the test suite.
        """
        if not goal.success_criteria:
            return []

        # Format prompt
        prompt = SUCCESS_CRITERIA_TEST_PROMPT.format(
            goal_name=goal.name,
            goal_description=goal.description,
            success_criteria_formatted=self._format_criteria(goal.success_criteria),
            node_names=", ".join(node_names or ["(not specified)"]),
            tool_names=", ".join(tool_names or ["(not specified)"]),
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
            system="You are a test generation expert. For each success criterion, call the submit_test tool with the test details.",
            tools=[SUBMIT_TEST_TOOL],
            tool_executor=tool_executor,
            max_iterations=20,
        )

        return self._create_tests_from_collected(collected_tests, goal.id)

    def generate_for_criterion(
        self,
        goal: Goal,
        criterion: SuccessCriterion,
        node_names: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> list[Test]:
        """
        Generate tests for a single success criterion.

        Args:
            goal: Goal containing the criterion
            criterion: Specific criterion to test
            node_names: Names of agent nodes
            tool_names: Names of tools available

        Returns:
            List of Test objects for the criterion
        """
        prompt = SUCCESS_CRITERIA_TEST_PROMPT.format(
            goal_name=goal.name,
            goal_description=goal.description,
            success_criteria_formatted=self._format_criterion(criterion),
            node_names=", ".join(node_names or ["(not specified)"]),
            tool_names=", ".join(tool_names or ["(not specified)"]),
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

    def _format_criteria(self, criteria: list[SuccessCriterion]) -> str:
        """Format success criteria for prompt."""
        lines = []
        for c in criteria:
            lines.append(self._format_criterion(c))
            lines.append("")
        return "\n".join(lines)

    def _format_criterion(self, criterion: SuccessCriterion) -> str:
        """Format a single criterion for prompt."""
        return f"""### Success Criterion: {criterion.id}
- Description: {criterion.description}
- Metric: {criterion.metric}
- Target: {criterion.target}
- Weight: {criterion.weight}
- Currently met: {criterion.met}"""

    def _create_tests_from_collected(
        self, collected: list[dict], goal_id: str
    ) -> list[Test]:
        """Create Test objects from tool call data."""
        tests = []
        for td in collected:
            test = Test(
                id=f"test_{uuid.uuid4().hex[:8]}",
                goal_id=goal_id,
                parent_criteria_id=td.get("criteria_id", "unknown"),
                test_type=TestType.SUCCESS_CRITERIA,
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
