"""
Single test executor.

Executes a single test against an agent and returns a TestResult.
"""

import asyncio
import inspect
import time
import traceback
from typing import Any, Protocol, runtime_checkable

from framework.testing.test_case import Test
from framework.testing.test_result import TestResult, ErrorCategory
from framework.testing.categorizer import ErrorCategorizer


class LLMJudge:
    """
    LLM-based judge for semantic evaluation of test results.

    Used by tests that need to evaluate semantic properties like
    "no hallucination" or "preserves meaning" that can't be checked
    with simple assertions.
    """

    def __init__(self):
        """Initialize the LLM judge."""
        self._client = None

    def _get_client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except ImportError:
                raise RuntimeError("anthropic package required for LLM judge")
        return self._client

    def evaluate(
        self,
        constraint: str,
        source_document: str,
        summary: str,
        criteria: str,
    ) -> dict[str, Any]:
        """
        Evaluate whether a summary meets a constraint.

        Args:
            constraint: The constraint being tested (e.g., "no-hallucination")
            source_document: The original document
            summary: The generated summary to evaluate
            criteria: Human-readable criteria for evaluation

        Returns:
            Dict with 'passes' (bool) and 'explanation' (str)
        """
        client = self._get_client()

        prompt = f"""You are evaluating whether a summary meets a specific constraint.

CONSTRAINT: {constraint}
CRITERIA: {criteria}

SOURCE DOCUMENT:
{source_document}

SUMMARY TO EVALUATE:
{summary}

Evaluate whether the summary meets the constraint. Be strict but fair.

Respond with JSON in this exact format:
{{"passes": true/false, "explanation": "brief explanation of your judgment"}}

Only output the JSON, nothing else."""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse the response
            import json
            text = response.content[0].text.strip()
            # Handle potential markdown code blocks
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            result = json.loads(text)
            return {
                "passes": bool(result.get("passes", False)),
                "explanation": result.get("explanation", "No explanation provided")
            }
        except Exception as e:
            # On error, fail the test with explanation
            return {
                "passes": False,
                "explanation": f"LLM judge error: {e}"
            }


@runtime_checkable
class AgentProtocol(Protocol):
    """Protocol for agent that can be tested."""

    def run(self, input: dict[str, Any]) -> Any:
        """Run the agent with input and return result."""
        ...


class SyncAgentWrapper:
    """
    Wrapper that makes async agent.run() callable synchronously.

    This allows tests to call agent.run() without async/await syntax,
    which simplifies test code generation and execution.
    """

    def __init__(self, agent: Any):
        self._agent = agent
        self._loop: asyncio.AbstractEventLoop | None = None

    def run(self, input_data: dict[str, Any]) -> Any:
        """
        Run agent synchronously by wrapping async call.

        Args:
            input_data: Input data for the agent

        Returns:
            Output dict from the agent's ExecutionResult
        """
        coro = self._agent.run(input_data)

        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            # We're in an async context, can't use run_until_complete
            # This shouldn't happen in normal test execution
            raise RuntimeError("Cannot run sync wrapper from async context")
        except RuntimeError:
            # No running loop, create one or reuse
            pass

        # Get or create event loop
        try:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            return self._loop.run_until_complete(coro).output
        finally:
            # Don't close the loop here - we may need it for subsequent calls
            pass

    def __getattr__(self, name: str) -> Any:
        """Forward other attribute access to wrapped agent."""
        return getattr(self._agent, name)


class TestExecutor:
    """
    Execute a single test against an agent.

    Handles:
    - Test code compilation and execution
    - Timing measurement
    - Error capture and categorization
    - Result creation
    """

    def __init__(
        self,
        categorizer: ErrorCategorizer | None = None,
        timeout: float = 60.0,
    ):
        """
        Initialize executor.

        Args:
            categorizer: ErrorCategorizer for classifying failures
            timeout: Maximum test execution time in seconds
        """
        self.categorizer = categorizer or ErrorCategorizer()
        self.timeout = timeout

    def execute(
        self,
        test: Test,
        agent: AgentProtocol,
        capture_logs: bool = True,
    ) -> TestResult:
        """
        Execute a test against an agent.

        Args:
            test: Test to execute
            agent: Agent instance to test
            capture_logs: Whether to capture runtime logs

        Returns:
            TestResult with execution details
        """
        start_time = time.perf_counter()

        try:
            # Build test environment
            test_globals = self._build_test_globals(agent, test)

            # Compile test code
            try:
                compiled = compile(test.test_code, f"<test:{test.test_name}>", "exec")
            except SyntaxError as e:
                return self._create_error_result(
                    test=test,
                    start_time=start_time,
                    error_message=f"Test code syntax error: {e}",
                    stack_trace=traceback.format_exc(),
                )

            # Execute test
            try:
                exec(compiled, test_globals)

                # Look for test function and call it
                test_func = test_globals.get(test.test_name)
                if test_func is None:
                    # Try to find any function starting with test_
                    for name, obj in test_globals.items():
                        if name.startswith("test_") and callable(obj):
                            test_func = obj
                            break

                if test_func is None:
                    return self._create_error_result(
                        test=test,
                        start_time=start_time,
                        error_message=f"Test function '{test.test_name}' not found in test code",
                    )

                # Call the test function with appropriate arguments
                # Inspect the function signature to determine what to pass
                sig = inspect.signature(test_func)
                params = list(sig.parameters.keys())

                # Build arguments based on what the function expects
                call_args = []
                for param in params:
                    if param == "agent":
                        call_args.append(test_globals["agent"])
                    elif param == "llm_judge":
                        call_args.append(test_globals["llm_judge"])
                    elif param in test_globals:
                        call_args.append(test_globals[param])
                    else:
                        # Unknown parameter - this will likely cause an error
                        # but we let it happen naturally
                        break

                test_func(*call_args)

                # Test passed
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                return TestResult(
                    test_id=test.id,
                    passed=True,
                    duration_ms=duration_ms,
                    expected_output=test.expected_output,
                    actual_output={"status": "passed"},
                )

            except AssertionError as e:
                return self._create_failure_result(
                    test=test,
                    start_time=start_time,
                    error_message=str(e) or "Assertion failed",
                    stack_trace=traceback.format_exc(),
                )

            except Exception as e:
                return self._create_failure_result(
                    test=test,
                    start_time=start_time,
                    error_message=f"{type(e).__name__}: {e}",
                    stack_trace=traceback.format_exc(),
                )

        except Exception as e:
            return self._create_error_result(
                test=test,
                start_time=start_time,
                error_message=f"Test execution error: {e}",
                stack_trace=traceback.format_exc(),
            )

    def _build_test_globals(
        self,
        agent: AgentProtocol,
        test: Test,
    ) -> dict[str, Any]:
        """Build the globals dict for test execution."""
        # Wrap async agents in a sync wrapper so test code can call agent.run()
        # without async/await syntax
        wrapped_agent = self._wrap_agent_if_async(agent)

        return {
            "__builtins__": __builtins__,
            "agent": wrapped_agent,
            "llm_judge": LLMJudge(),  # For semantic evaluation tests
            "test_input": test.input,
            "expected_output": test.expected_output,
            # Common test utilities
            "assert": assert_,  # Built-in
            "isinstance": isinstance,
            "len": len,
            "str": str,
            "int": int,
            "float": float,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "any": any,
            "all": all,
            "print": print,  # For debugging
        }

    def _wrap_agent_if_async(self, agent: AgentProtocol) -> Any:
        """
        Wrap agent if its run() method is async.

        Args:
            agent: Agent to potentially wrap

        Returns:
            SyncAgentWrapper if agent.run() is async, otherwise the original agent
        """
        run_method = getattr(agent, "run", None)
        if run_method is None:
            return agent

        # Check if run() is a coroutine function
        if inspect.iscoroutinefunction(run_method):
            return SyncAgentWrapper(agent)

        return agent

    def _create_failure_result(
        self,
        test: Test,
        start_time: float,
        error_message: str,
        stack_trace: str | None = None,
    ) -> TestResult:
        """Create a result for a test that failed assertions."""
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        result = TestResult(
            test_id=test.id,
            passed=False,
            duration_ms=duration_ms,
            expected_output=test.expected_output,
            error_message=error_message,
            stack_trace=stack_trace,
        )

        # Categorize the error
        result.error_category = self.categorizer.categorize(result)

        return result

    def _create_error_result(
        self,
        test: Test,
        start_time: float,
        error_message: str,
        stack_trace: str | None = None,
    ) -> TestResult:
        """Create a result for a test that couldn't run."""
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        result = TestResult(
            test_id=test.id,
            passed=False,
            duration_ms=duration_ms,
            error_message=error_message,
            stack_trace=stack_trace,
        )

        # Implementation error for test setup failures
        result.error_category = ErrorCategory.IMPLEMENTATION_ERROR

        return result


def assert_(condition: bool, message: str = "") -> None:
    """Assert helper with message."""
    if not condition:
        raise AssertionError(message)
