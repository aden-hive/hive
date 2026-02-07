"""Health check system for Hive framework.

Provides health monitoring for:
- Service readiness and liveness
- Dependency health (LLM providers, storage, cache)
- Performance metrics and thresholds

Usage:
    from framework.health import HealthChecker, get_health

    health = get_health()

    # Register custom checks
    health.register("my-service", my_check_fn)

    # Get overall health
    status = await health.check_all()
    print(status.is_healthy)

    # Use as HTTP endpoint
    @app.get("/health")
    async def health_endpoint():
        return await health.to_response()
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class HealthStatus(StrEnum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY


@dataclass
class HealthReport:
    """Complete health report with all check results."""

    status: HealthStatus
    checks: list[CheckResult]
    timestamp: float = field(default_factory=time.time)
    version: str = "1.0.0"

    @property
    def is_healthy(self) -> bool:
        return self.status == HealthStatus.HEALTHY

    @property
    def is_ready(self) -> bool:
        """Check if service is ready to receive traffic."""
        return self.status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON response."""
        return {
            "status": self.status.value,
            "is_healthy": self.is_healthy,
            "is_ready": self.is_ready,
            "timestamp": self.timestamp,
            "version": self.version,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "latency_ms": round(c.latency_ms, 2),
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


# Type for health check functions
HealthCheckFn = Callable[[], CheckResult | None]
AsyncHealthCheckFn = Callable[[], CheckResult | None]


class HealthChecker:
    """Health checker with pluggable checks.

    Supports both sync and async health check functions.
    Aggregates results and determines overall health status.
    """

    def __init__(self, version: str = "1.0.0"):
        self.version = version
        self._checks: dict[str, Callable] = {}
        self._thresholds = {
            "unhealthy_threshold": 1,  # Number of critical failures for unhealthy
            "degraded_threshold": 1,  # Number of degraded checks for degraded
            "check_timeout": 5.0,  # Timeout per check in seconds
        }

    def register(
        self,
        name: str,
        check_fn: Callable,
        critical: bool = True,
    ) -> None:
        """Register a health check function.

        Args:
            name: Unique name for the check
            check_fn: Sync or async function that returns CheckResult
            critical: If True, failure makes service unhealthy vs degraded
        """
        self._checks[name] = {"fn": check_fn, "critical": critical}
        logger.debug(f"Registered health check: {name} (critical={critical})")

    def unregister(self, name: str) -> None:
        """Unregister a health check."""
        if name in self._checks:
            del self._checks[name]

    async def check(self, name: str) -> CheckResult:
        """Run a single health check by name."""
        if name not in self._checks:
            return CheckResult(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Check '{name}' not found",
            )

        check_info = self._checks[name]
        check_fn = check_info["fn"]

        start = time.time()
        try:
            if asyncio.iscoroutinefunction(check_fn):
                result = await asyncio.wait_for(
                    check_fn(), timeout=self._thresholds["check_timeout"]
                )
            else:
                result = check_fn()

            if result is None:
                result = CheckResult(
                    name=name,
                    status=HealthStatus.HEALTHY,
                    message="OK",
                )
            elif not isinstance(result, CheckResult):
                result = CheckResult(
                    name=name,
                    status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                    message=str(result),
                )

            result.latency_ms = (time.time() - start) * 1000
            return result

        except asyncio.TimeoutError:
            return CheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message="Check timed out",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return CheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def check_all(self) -> HealthReport:
        """Run all registered health checks.

        Returns:
            Complete health report with overall status
        """
        # Run all checks concurrently
        tasks = [self.check(name) for name in self._checks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to CheckResults
        checks = []
        for i, result in enumerate(results):
            name = list(self._checks.keys())[i]
            if isinstance(result, Exception):
                checks.append(
                    CheckResult(
                        name=name,
                        status=HealthStatus.UNHEALTHY,
                        message=str(result),
                    )
                )
            else:
                checks.append(result)

        # Determine overall status
        critical_failures = 0
        degraded_count = 0

        for check in checks:
            check_info = self._checks.get(check.name, {})
            is_critical = check_info.get("critical", True)

            if check.status == HealthStatus.UNHEALTHY:
                if is_critical:
                    critical_failures += 1
                else:
                    degraded_count += 1
            elif check.status == HealthStatus.DEGRADED:
                degraded_count += 1

        if critical_failures >= self._thresholds["unhealthy_threshold"]:
            overall_status = HealthStatus.UNHEALTHY
        elif degraded_count >= self._thresholds["degraded_threshold"]:
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return HealthReport(
            status=overall_status,
            checks=checks,
            version=self.version,
        )

    async def liveness(self) -> HealthReport:
        """Quick liveness check (is the service running?)."""
        return HealthReport(
            status=HealthStatus.HEALTHY,
            checks=[
                CheckResult(
                    name="liveness",
                    status=HealthStatus.HEALTHY,
                    message="Service is alive",
                )
            ],
            version=self.version,
        )

    async def readiness(self) -> HealthReport:
        """Readiness check (is the service ready for traffic?)."""
        report = await self.check_all()
        return report


# =============================================================================
# Built-in health checks
# =============================================================================


def check_memory() -> CheckResult:
    """Check system memory usage."""
    try:
        import psutil

        memory = psutil.virtual_memory()
        used_percent = memory.percent

        if used_percent > 95:
            status = HealthStatus.UNHEALTHY
            message = f"Memory critically high: {used_percent}%"
        elif used_percent > 85:
            status = HealthStatus.DEGRADED
            message = f"Memory high: {used_percent}%"
        else:
            status = HealthStatus.HEALTHY
            message = f"Memory OK: {used_percent}%"

        return CheckResult(
            name="memory",
            status=status,
            message=message,
            details={
                "used_percent": used_percent,
                "available_mb": memory.available // (1024 * 1024),
                "total_mb": memory.total // (1024 * 1024),
            },
        )
    except ImportError:
        return CheckResult(
            name="memory",
            status=HealthStatus.UNKNOWN,
            message="psutil not installed",
        )


def check_disk(path: str = "/") -> CheckResult:
    """Check disk usage for a path."""
    try:
        import psutil

        disk = psutil.disk_usage(path)
        used_percent = disk.percent

        if used_percent > 95:
            status = HealthStatus.UNHEALTHY
            message = f"Disk critically full: {used_percent}%"
        elif used_percent > 85:
            status = HealthStatus.DEGRADED
            message = f"Disk high: {used_percent}%"
        else:
            status = HealthStatus.HEALTHY
            message = f"Disk OK: {used_percent}%"

        return CheckResult(
            name="disk",
            status=status,
            message=message,
            details={
                "path": path,
                "used_percent": used_percent,
                "free_gb": disk.free // (1024 * 1024 * 1024),
                "total_gb": disk.total // (1024 * 1024 * 1024),
            },
        )
    except ImportError:
        return CheckResult(
            name="disk",
            status=HealthStatus.UNKNOWN,
            message="psutil not installed",
        )


async def check_llm_provider(provider: str, model: str | None = None) -> CheckResult:
    """Check LLM provider connectivity."""
    import os

    env_key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "cerebras": "CEREBRAS_API_KEY",
    }

    env_key = env_key_map.get(provider)
    if not env_key or not os.environ.get(env_key):
        return CheckResult(
            name=f"llm.{provider}",
            status=HealthStatus.DEGRADED,
            message=f"API key not configured ({env_key})",
        )

    try:
        # Try a minimal API call
        if provider == "anthropic":
            import anthropic

            client = anthropic.AsyncAnthropic()
            # Just validate we can create a client
            # (actual API call would cost money)
            return CheckResult(
                name=f"llm.{provider}",
                status=HealthStatus.HEALTHY,
                message="Client initialized successfully",
            )
        elif provider == "openai":
            import openai

            client = openai.AsyncOpenAI()
            return CheckResult(
                name=f"llm.{provider}",
                status=HealthStatus.HEALTHY,
                message="Client initialized successfully",
            )
        else:
            return CheckResult(
                name=f"llm.{provider}",
                status=HealthStatus.UNKNOWN,
                message=f"Unknown provider: {provider}",
            )
    except Exception as e:
        return CheckResult(
            name=f"llm.{provider}",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )


async def check_redis(url: str) -> CheckResult:
    """Check Redis connectivity."""
    try:
        import redis.asyncio as redis

        client = redis.from_url(url)
        await client.ping()
        info = await client.info("server")
        await client.close()

        return CheckResult(
            name="redis",
            status=HealthStatus.HEALTHY,
            message="Connected",
            details={
                "version": info.get("redis_version", "unknown"),
            },
        )
    except ImportError:
        return CheckResult(
            name="redis",
            status=HealthStatus.UNKNOWN,
            message="redis package not installed",
        )
    except Exception as e:
        return CheckResult(
            name="redis",
            status=HealthStatus.UNHEALTHY,
            message=str(e),
        )


# =============================================================================
# Global health checker
# =============================================================================

_global_health: HealthChecker | None = None


def get_health(version: str = "1.0.0") -> HealthChecker:
    """Get or create the global health checker."""
    global _global_health

    if _global_health is None:
        _global_health = HealthChecker(version=version)
        # Register default checks
        _global_health.register("memory", check_memory, critical=False)

    return _global_health


def reset_health() -> None:
    """Reset the global health checker."""
    global _global_health
    _global_health = None


__all__ = [
    "HealthChecker",
    "HealthStatus",
    "HealthReport",
    "CheckResult",
    "get_health",
    "reset_health",
    # Built-in checks
    "check_memory",
    "check_disk",
    "check_llm_provider",
    "check_redis",
]
