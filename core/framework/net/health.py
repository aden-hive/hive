"""
Health check framework — inspired by GitHub status checks and
TestSprite-style continuous validation patterns.

Supports:
- Endpoint health checks (HTTP, TCP, custom)
- GitHub API status checks (repo CI, code scanning, branch protection)
- Composite checks (all/any must pass)
- Continuous monitoring with configurable intervals
- Callback notifications on state change
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import httpx

logger = logging.getLogger("framework.net.health")


class HealthStatus(StrEnum):
    """Status values aligned with GitHub commit status API."""

    HEALTHY = "success"
    DEGRADED = "warning"
    UNHEALTHY = "failure"
    PENDING = "pending"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    """Result of a single health check execution."""

    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


class BaseHealthCheck(ABC):
    """Base class for all health checks."""

    def __init__(self, name: str, timeout: float = 10.0):
        self.name = name
        self.timeout = timeout

    @abstractmethod
    async def check(self) -> CheckResult:
        """Execute the health check and return a result."""
        ...

    async def timed_check(self) -> CheckResult:
        """Execute with timing and error handling."""
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(self.check(), timeout=self.timeout)
            result.latency_ms = (time.monotonic() - start) * 1000
            return result
        except TimeoutError:
            return CheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Timed out after {self.timeout}s",
                latency_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {e}",
                latency_ms=(time.monotonic() - start) * 1000,
            )


class HttpHealthCheck(BaseHealthCheck):
    """HTTP endpoint health check."""

    def __init__(
        self,
        name: str,
        url: str,
        *,
        method: str = "GET",
        expected_status: int = 200,
        headers: dict[str, str] | None = None,
        timeout: float = 10.0,
    ):
        super().__init__(name, timeout)
        self.url = url
        self.method = method
        self.expected_status = expected_status
        self.headers = headers or {}

    async def check(self) -> CheckResult:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.request(self.method, self.url, headers=self.headers)
            if resp.status_code == self.expected_status:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message=f"HTTP {resp.status_code}",
                    metadata={"url": self.url, "status_code": resp.status_code},
                )
            return CheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"Expected {self.expected_status}, got {resp.status_code}",
                metadata={"url": self.url, "status_code": resp.status_code},
            )


class TcpHealthCheck(BaseHealthCheck):
    """TCP port connectivity check."""

    def __init__(self, name: str, host: str, port: int, *, timeout: float = 5.0):
        super().__init__(name, timeout)
        self.host = host
        self.port = port

    async def check(self) -> CheckResult:
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=self.timeout,
            )
            writer.close()
            await writer.wait_closed()
            return CheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"TCP {self.host}:{self.port} reachable",
                metadata={"host": self.host, "port": self.port},
            )
        except (ConnectionRefusedError, OSError) as e:
            return CheckResult(
                name=self.name,
                status=HealthStatus.UNHEALTHY,
                message=f"TCP {self.host}:{self.port} unreachable: {e}",
                metadata={"host": self.host, "port": self.port},
            )


class GitHubStatusCheck(BaseHealthCheck):
    """
    Check GitHub repo status — CI checks, code scanning alerts, branch protection.
    Mirrors the GitHub commit status / check-runs API pattern.
    """

    def __init__(
        self,
        name: str,
        owner: str,
        repo: str,
        *,
        token: str | None = None,
        branch: str = "main",
        required_checks: list[str] | None = None,
        timeout: float = 15.0,
    ):
        super().__init__(name, timeout)
        self.owner = owner
        self.repo = repo
        self.token = token
        self.branch = branch
        self.required_checks = required_checks or []

    async def check(self) -> CheckResult:
        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Get combined status for the branch HEAD
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/commits/{self.branch}/status"
            )
            resp = await client.get(url, headers=headers)

            if resp.status_code == 404:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message=f"Repo {self.owner}/{self.repo} not found or no access",
                )

            if resp.status_code != 200:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message=f"GitHub API returned {resp.status_code}",
                )

            data = resp.json()
            state = data.get("state", "unknown")

            # Also fetch check runs for richer data
            check_runs_url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/commits/{self.branch}/check-runs"
            )
            runs_resp = await client.get(check_runs_url, headers=headers)
            check_runs: list[dict[str, Any]] = []
            failed_checks: list[str] = []
            if runs_resp.status_code == 200:
                runs_data = runs_resp.json()
                check_runs = runs_data.get("check_runs", [])

                for run in check_runs:
                    run_name = run.get("name", "")
                    conclusion = run.get("conclusion")
                    run_status = run.get("status")

                    if run_name in self.required_checks:
                        if conclusion not in ("success", "skipped"):
                            failed_checks.append(f"{run_name}: {conclusion or run_status}")

            if failed_checks:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=f"Required checks failing: {', '.join(failed_checks)}",
                    metadata={
                        "state": state,
                        "total_checks": len(check_runs),
                        "failed": failed_checks,
                    },
                )

            status_map = {
                "success": HealthStatus.HEALTHY,
                "pending": HealthStatus.PENDING,
                "failure": HealthStatus.UNHEALTHY,
                "error": HealthStatus.UNHEALTHY,
            }

            return CheckResult(
                name=self.name,
                status=status_map.get(state, HealthStatus.UNKNOWN),
                message=f"GitHub combined status: {state}",
                metadata={
                    "state": state,
                    "total_statuses": data.get("total_count", 0),
                    "total_check_runs": len(check_runs),
                },
            )


class CodeScanningCheck(BaseHealthCheck):
    """Check GitHub Code Scanning alerts — zero open critical/high = healthy."""

    def __init__(
        self,
        name: str,
        owner: str,
        repo: str,
        *,
        token: str,
        max_critical: int = 0,
        max_high: int = 0,
        timeout: float = 15.0,
    ):
        super().__init__(name, timeout)
        self.owner = owner
        self.repo = repo
        self.token = token
        self.max_critical = max_critical
        self.max_high = max_high

    async def check(self) -> CheckResult:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = (
                f"https://api.github.com/repos/{self.owner}/{self.repo}"
                f"/code-scanning/alerts?state=open&per_page=100"
            )
            resp = await client.get(url, headers=headers)

            if resp.status_code == 404:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.HEALTHY,
                    message="Code scanning not configured or no alerts",
                )

            if resp.status_code != 200:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.UNKNOWN,
                    message=f"GitHub API returned {resp.status_code}",
                )

            alerts = resp.json()
            critical = sum(
                1
                for a in alerts
                if a.get("rule", {}).get("security_severity_level") == "critical"
            )
            high = sum(
                1
                for a in alerts
                if a.get("rule", {}).get("security_severity_level") == "high"
            )

            if critical > self.max_critical or high > self.max_high:
                return CheckResult(
                    name=self.name,
                    status=HealthStatus.UNHEALTHY,
                    message=(
                        f"{critical} critical, {high} high alerts "
                        f"(max: {self.max_critical}/{self.max_high})"
                    ),
                    metadata={"critical": critical, "high": high, "total_open": len(alerts)},
                )

            return CheckResult(
                name=self.name,
                status=HealthStatus.HEALTHY,
                message=f"{len(alerts)} open alerts ({critical} critical, {high} high)",
                metadata={"critical": critical, "high": high, "total_open": len(alerts)},
            )


class CompositeHealthCheck(BaseHealthCheck):
    """
    Combines multiple checks — TestSprite-style continuous validation.

    Modes:
    - ``all``: all checks must pass (AND logic)
    - ``any``: at least one check must pass (OR logic)
    - ``majority``: >50% must pass
    """

    def __init__(
        self,
        name: str,
        checks: list[BaseHealthCheck],
        *,
        mode: str = "all",
        timeout: float = 30.0,
    ):
        super().__init__(name, timeout)
        self.checks = checks
        self.mode = mode

    async def check(self) -> CheckResult:
        results_raw = await asyncio.gather(
            *(c.timed_check() for c in self.checks),
            return_exceptions=True,
        )

        check_results: list[CheckResult] = []
        for r in results_raw:
            if isinstance(r, Exception):
                check_results.append(
                    CheckResult(name="unknown", status=HealthStatus.UNHEALTHY, message=str(r))
                )
            else:
                check_results.append(r)

        healthy_count = sum(1 for r in check_results if r.is_healthy)
        total = len(check_results)

        if self.mode == "all":
            overall = HealthStatus.HEALTHY if healthy_count == total else HealthStatus.UNHEALTHY
        elif self.mode == "any":
            overall = HealthStatus.HEALTHY if healthy_count > 0 else HealthStatus.UNHEALTHY
        elif self.mode == "majority":
            overall = HealthStatus.HEALTHY if healthy_count > total / 2 else HealthStatus.UNHEALTHY
        else:
            overall = HealthStatus.UNKNOWN

        return CheckResult(
            name=self.name,
            status=overall,
            message=f"{healthy_count}/{total} checks passed (mode={self.mode})",
            metadata={
                "results": [r.to_dict() for r in check_results],
                "healthy": healthy_count,
                "total": total,
                "mode": self.mode,
            },
        )


class HealthChecker:
    """
    Continuous health monitoring — runs checks on a schedule,
    tracks history, and fires callbacks on state transitions.

    Similar to TestSprite continuous validation + GitHub required status check pattern.
    """

    def __init__(
        self,
        checks: list[BaseHealthCheck],
        *,
        interval: float = 60.0,
        on_state_change: Callable[[CheckResult, CheckResult], None] | None = None,
        history_size: int = 100,
    ):
        self.checks = checks
        self.interval = interval
        self.on_state_change = on_state_change
        self.history_size = history_size
        self._history: dict[str, list[CheckResult]] = {}
        self._last_status: dict[str, HealthStatus] = {}
        self._running = False
        self._task: asyncio.Task[None] | None = None

    @property
    def latest_results(self) -> dict[str, CheckResult]:
        """Get the most recent result for each check."""
        return {name: history[-1] for name, history in self._history.items() if history}

    @property
    def overall_status(self) -> HealthStatus:
        """Aggregate status across all checks — all must be healthy."""
        results = self.latest_results
        if not results:
            return HealthStatus.UNKNOWN
        if all(r.is_healthy for r in results.values()):
            return HealthStatus.HEALTHY
        if any(r.status == HealthStatus.UNHEALTHY for r in results.values()):
            return HealthStatus.UNHEALTHY
        return HealthStatus.DEGRADED

    async def run_once(self) -> list[CheckResult]:
        """Run all checks once and return results."""
        results_raw = await asyncio.gather(
            *(check.timed_check() for check in self.checks),
            return_exceptions=True,
        )

        processed: list[CheckResult] = []
        for r in results_raw:
            if isinstance(r, Exception):
                result = CheckResult(name="error", status=HealthStatus.UNHEALTHY, message=str(r))
            else:
                result = r

            # Track history
            if result.name not in self._history:
                self._history[result.name] = []
            self._history[result.name].append(result)
            if len(self._history[result.name]) > self.history_size:
                self._history[result.name] = self._history[result.name][-self.history_size :]

            # Detect state changes
            prev_status = self._last_status.get(result.name, HealthStatus.UNKNOWN)
            if result.status != prev_status and self.on_state_change:
                prev_result = CheckResult(
                    name=result.name, status=prev_status, message="(previous)"
                )
                try:
                    self.on_state_change(prev_result, result)
                except Exception:
                    logger.exception("on_state_change callback failed")
            self._last_status[result.name] = result.status

            processed.append(result)

        return processed

    async def start(self) -> None:
        """Start continuous monitoring."""
        self._running = True
        logger.info(
            "Health checker started: %d checks, interval=%ss",
            len(self.checks),
            self.interval,
        )
        while self._running:
            try:
                await self.run_once()
            except Exception:
                logger.exception("Health check cycle failed")
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        """Stop continuous monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def summary(self) -> dict[str, Any]:
        """Return a full status summary suitable for API/TUI display."""
        results = self.latest_results
        return {
            "overall": self.overall_status.value,
            "checks": {name: r.to_dict() for name, r in results.items()},
            "total": len(results),
            "healthy": sum(1 for r in results.values() if r.is_healthy),
        }
