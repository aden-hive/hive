"""
TestSprite-inspired continuous test runner.

Runs validation suites on schedules or triggers, reports results
through the health check framework, and integrates with GitHub
status checks for approved merge patterns.

Patterns:
- Pre-merge validation gates
- Post-deploy smoke tests
- Continuous canary testing
- Scheduled regression sweeps
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from framework.net.health import BaseHealthCheck, CheckResult, HealthStatus

logger = logging.getLogger("framework.net.test_runner")


class TestSuite(StrEnum):
    UNIT = "unit"
    INTEGRATION = "integration"
    SMOKE = "smoke"
    E2E = "e2e"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class TestConfig:
    """Configuration for a test suite."""

    name: str
    suite: TestSuite
    command: str  # Shell command to run
    timeout: float = 300.0  # 5 minutes default
    required_for_merge: bool = True
    schedule_interval: float | None = None  # Seconds; None = on-demand only
    working_dir: str = "."
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class TestResult:
    """Result of a test suite execution."""

    config: TestConfig
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    timestamp: float = field(default_factory=time.time)

    def to_check_result(self) -> CheckResult:
        return CheckResult(
            name=f"test:{self.config.name}",
            status=HealthStatus.HEALTHY if self.passed else HealthStatus.UNHEALTHY,
            message=(
                f"{self.config.suite.value} tests "
                f"{'passed' if self.passed else 'FAILED'} "
                f"in {self.duration_ms:.0f}ms"
            ),
            latency_ms=self.duration_ms,
            metadata={
                "suite": self.config.suite.value,
                "exit_code": self.exit_code,
                "command": self.config.command,
                "stdout_tail": self.stdout[-500:] if self.stdout else "",
                "stderr_tail": self.stderr[-500:] if self.stderr else "",
            },
        )


class TestSuiteCheck(BaseHealthCheck):
    """Health check that runs a test suite."""

    def __init__(self, config: TestConfig):
        super().__init__(f"test:{config.name}", timeout=config.timeout)
        self.config = config

    async def check(self) -> CheckResult:
        result = await run_test_suite(self.config)
        return result.to_check_result()


async def run_test_suite(config: TestConfig) -> TestResult:
    """Run a single test suite asynchronously."""
    start = time.monotonic()

    try:
        merged_env = {**os.environ, **config.env} if config.env else None
        proc = await asyncio.create_subprocess_shell(
            config.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=config.working_dir,
            env=merged_env,
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=config.timeout,
        )

        duration = (time.monotonic() - start) * 1000
        exit_code = proc.returncode or 0

        return TestResult(
            config=config,
            passed=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            duration_ms=duration,
        )
    except TimeoutError:
        duration = (time.monotonic() - start) * 1000
        return TestResult(
            config=config,
            passed=False,
            exit_code=-1,
            stdout="",
            stderr=f"Test suite timed out after {config.timeout}s",
            duration_ms=duration,
        )
    except Exception as e:
        duration = (time.monotonic() - start) * 1000
        return TestResult(
            config=config,
            passed=False,
            exit_code=-1,
            stdout="",
            stderr=str(e),
            duration_ms=duration,
        )


class ContinuousTestRunner:
    """
    TestSprite-style runner: continuously runs test suites,
    reports via health checks, and gates merges on results.
    """

    def __init__(
        self,
        suites: list[TestConfig],
        *,
        on_result: Callable[[TestResult], None] | None = None,
    ):
        self.suites = suites
        self.on_result = on_result
        self._results: dict[str, TestResult] = {}
        self._running = False

    @property
    def merge_ready(self) -> bool:
        """Are all required-for-merge suites passing?"""
        for suite in self.suites:
            if suite.required_for_merge:
                result = self._results.get(suite.name)
                if result is None or not result.passed:
                    return False
        return True

    @property
    def gate_summary(self) -> dict[str, Any]:
        """Summary suitable for display as a merge gate."""
        checks = []
        for suite in self.suites:
            result = self._results.get(suite.name)
            checks.append(
                {
                    "name": suite.name,
                    "suite": suite.suite.value,
                    "required": suite.required_for_merge,
                    "status": (
                        "passed"
                        if result and result.passed
                        else "failed"
                        if result
                        else "pending"
                    ),
                    "duration_ms": result.duration_ms if result else None,
                }
            )

        return {
            "merge_ready": self.merge_ready,
            "checks": checks,
            "total": len(checks),
            "passing": sum(1 for c in checks if c["status"] == "passed"),
        }

    async def run_all(self) -> list[TestResult]:
        """Run all suites once."""
        results = []
        for suite in self.suites:
            result = await run_test_suite(suite)
            self._results[suite.name] = result
            results.append(result)
            if self.on_result:
                try:
                    self.on_result(result)
                except Exception:
                    logger.exception("on_result callback failed")
        return results

    async def run_scheduled(self) -> None:
        """Run scheduled suites continuously."""
        self._running = True
        tasks = []
        for suite in self.suites:
            if suite.schedule_interval:
                tasks.append(asyncio.create_task(self._schedule_suite(suite)))

        if tasks:
            await asyncio.gather(*tasks)

    async def _schedule_suite(self, suite: TestConfig) -> None:
        assert suite.schedule_interval is not None
        while self._running:
            result = await run_test_suite(suite)
            self._results[suite.name] = result
            if self.on_result:
                try:
                    self.on_result(result)
                except Exception:
                    logger.exception("on_result callback failed")
            await asyncio.sleep(suite.schedule_interval)

    def stop(self) -> None:
        self._running = False

    def get_health_checks(self) -> list[BaseHealthCheck]:
        """Convert suites to health checks for integration with HealthChecker."""
        return [TestSuiteCheck(suite) for suite in self.suites]
