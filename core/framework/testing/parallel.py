"""
Parallel test runner inspired by pytest-xdist.

Features:
- Per-test parallelism: Each test runs independently with load balancing
- Worker initialization: Agent created once per worker thread (not per test)
- Thread-based parallelism: Uses ThreadPoolExecutor for I/O-bound LLM calls
- Fail-fast option: Stop on first failure
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from multiprocessing import cpu_count
from typing import Any, Callable, Protocol, runtime_checkable

from framework.testing.test_case import Test
from framework.testing.test_result import TestResult, TestSuiteResult
from framework.testing.test_storage import TestStorage
from framework.testing.executor import TestExecutor, AgentProtocol
from framework.testing.categorizer import ErrorCategorizer


# Thread-local storage for worker agents
# Each worker thread gets its own agent instance to avoid race conditions
_thread_local = threading.local()


def _init_worker(agent_factory: Any) -> None:
    """
    Initialize worker thread with its own agent instance.

    Called once per worker thread when the ThreadPoolExecutor starts.
    The agent is stored in thread-local storage and reused for all tests
    executed by this worker.
    """
    if hasattr(agent_factory, "create"):
        _thread_local.agent = agent_factory.create()
    else:
        _thread_local.agent = agent_factory()


def _run_single_test(test: Test, timeout: float) -> TestResult:
    """
    Run a single test using the worker's pre-initialized agent.

    Args:
        test: Test to execute
        timeout: Timeout per test in seconds

    Returns:
        TestResult with execution details
    """
    executor = TestExecutor(
        categorizer=ErrorCategorizer(),
        timeout=timeout,
    )
    return executor.execute(test, _thread_local.agent)


@dataclass
class ParallelConfig:
    """Configuration for parallel test execution."""

    num_workers: int = field(default_factory=cpu_count)
    timeout_per_test: float = 60.0  # seconds
    fail_fast: bool = False
    mock_external_apis: bool = True


@runtime_checkable
class AgentFactoryProtocol(Protocol):
    """Protocol for creating agent instances."""

    def create(self) -> AgentProtocol:
        """Create a new agent instance."""
        ...


class AgentFactory:
    """Picklable factory that creates AgentRunner instances from a path.

    This class is used instead of a lambda for parallel test execution,
    since lambdas capturing local variables cannot be pickled by ProcessPoolExecutor.
    """

    def __init__(self, agent_path: str):
        self.agent_path = agent_path

    def create(self):
        from framework.runner import AgentRunner
        return AgentRunner.load(self.agent_path)


class ParallelTestRunner:
    """
    Parallel test execution using ThreadPoolExecutor.

    Key features:
    - Per-test distribution: Tests distributed individually for load balancing
    - Worker initialization: Each worker thread creates one agent at startup
    - Thread-based parallelism: Uses threads (not processes) for I/O-bound LLM calls
    - Thread-local storage: Each worker has isolated agent state via threading.local()
    """

    def __init__(
        self,
        config: ParallelConfig | None = None,
        storage: TestStorage | None = None,
    ):
        """
        Initialize parallel runner.

        Args:
            config: Parallel execution configuration
            storage: TestStorage for saving results
        """
        self.config = config or ParallelConfig()
        self.storage = storage
        self.categorizer = ErrorCategorizer()

    def run_all(
        self,
        goal_id: str,
        agent_factory: AgentFactoryProtocol | Callable[[], AgentProtocol],
        tests: list[Test] | None = None,
        on_result: Callable[[TestResult], None] | None = None,
    ) -> TestSuiteResult:
        """
        Run all approved tests for a goal.

        Args:
            goal_id: Goal ID to run tests for
            agent_factory: Factory for creating agent instances
            tests: Optional list of tests (loads from storage if not provided)
            on_result: Optional callback for each test result

        Returns:
            TestSuiteResult with summary and individual results
        """
        # Load tests if not provided
        if tests is None:
            if self.storage is None:
                raise ValueError("Either tests or storage must be provided")
            tests = self.storage.get_approved_tests(goal_id)

        if not tests:
            return TestSuiteResult(
                goal_id=goal_id,
                total=0,
                passed=0,
                failed=0,
            )

        # Execute tests
        results: list[TestResult] = []

        if self.config.num_workers <= 1:
            # Sequential execution - create single agent and run all tests
            results = self._run_sequential(tests, agent_factory, on_result)
        else:
            # Parallel execution with per-test distribution
            results = self._run_parallel(tests, agent_factory, on_result)

        # Save results if storage available
        if self.storage:
            # Create test_id -> test mapping for lookup
            test_map = {t.id: t for t in tests}

            for result in results:
                # Update the Test object with execution result
                if result.test_id in test_map:
                    test = test_map[result.test_id]
                    test.record_result(result.passed)
                    self.storage.update_test(test)

                # Save the TestResult
                self.storage.save_result(result.test_id, result)

        # Create suite result
        return self._create_suite_result(goal_id, results)

    def run_tests(
        self,
        tests: list[Test],
        agent: AgentProtocol,
        on_result: Callable[[TestResult], None] | None = None,
    ) -> list[TestResult]:
        """
        Run a list of tests against an agent instance.

        Args:
            tests: Tests to run
            agent: Agent instance to test
            on_result: Optional callback for each result

        Returns:
            List of TestResult
        """
        executor = TestExecutor(
            categorizer=self.categorizer,
            timeout=self.config.timeout_per_test,
        )

        results = []
        for test in tests:
            result = executor.execute(test, agent)
            results.append(result)

            if on_result:
                on_result(result)

            # Fail-fast check
            if self.config.fail_fast and not result.passed:
                break

        return results

    def _run_sequential(
        self,
        tests: list[Test],
        agent_factory: AgentFactoryProtocol | Callable[[], AgentProtocol],
        on_result: Callable[[TestResult], None] | None = None,
    ) -> list[TestResult]:
        """Run tests sequentially with a single agent instance."""
        results = []
        executor = TestExecutor(
            categorizer=self.categorizer,
            timeout=self.config.timeout_per_test,
        )

        # Create single agent for all tests
        if isinstance(agent_factory, AgentFactoryProtocol):
            agent = agent_factory.create()
        else:
            agent = agent_factory()

        # Run all tests
        for test in tests:
            result = executor.execute(test, agent)
            results.append(result)

            if on_result:
                on_result(result)

            # Fail-fast
            if self.config.fail_fast and not result.passed:
                return results

        return results

    def _run_parallel(
        self,
        tests: list[Test],
        agent_factory: AgentFactoryProtocol | Callable[[], AgentProtocol],
        on_result: Callable[[TestResult], None] | None = None,
    ) -> list[TestResult]:
        """
        Run tests in parallel using ThreadPoolExecutor with worker initialization.

        Each worker thread creates ONE agent instance at startup and reuses it
        for all tests assigned to that worker. Tests are distributed individually
        for true load-balanced parallelism.

        Uses threads instead of processes because LLM API calls are I/O-bound,
        and threads have lower overhead (no pickling, shared memory).
        """
        results = []
        failed = False

        with ThreadPoolExecutor(
            max_workers=self.config.num_workers,
            initializer=_init_worker,
            initargs=(agent_factory,),
        ) as executor:
            # Submit each test individually for true parallelism
            futures = {
                executor.submit(_run_single_test, test, self.config.timeout_per_test): test
                for test in tests
            }

            for future in as_completed(futures):
                test = futures[future]
                try:
                    result = future.result(timeout=self.config.timeout_per_test + 30)
                    results.append(result)

                    if on_result:
                        on_result(result)

                    if not result.passed:
                        failed = True

                except TimeoutError:
                    result = TestResult(
                        test_id=test.id,
                        passed=False,
                        duration_ms=int(self.config.timeout_per_test * 1000),
                        error_message="Test timed out",
                    )
                    results.append(result)
                    if on_result:
                        on_result(result)
                    failed = True

                except Exception as e:
                    result = TestResult(
                        test_id=test.id,
                        passed=False,
                        duration_ms=0,
                        error_message=f"Execution error: {e}",
                    )
                    results.append(result)
                    if on_result:
                        on_result(result)
                    failed = True

                # Fail-fast
                if self.config.fail_fast and failed:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

        return results

    def _create_suite_result(
        self,
        goal_id: str,
        results: list[TestResult],
    ) -> TestSuiteResult:
        """Create TestSuiteResult from individual results."""
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        total_duration = sum(r.duration_ms for r in results)

        return TestSuiteResult(
            goal_id=goal_id,
            total=len(results),
            passed=passed,
            failed=failed,
            results=results,
            duration_ms=total_duration,
        )


