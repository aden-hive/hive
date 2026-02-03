"""
health check module for production deployments.

provides health and readiness checks for kubernetes or other
container orchestration systems.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """health status of a single component."""

    name: str
    healthy: bool
    message: str = ""
    error: str | None = None
    last_check: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """overall health report."""

    status: HealthStatus
    components: dict[str, ComponentHealth]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """convert to dict for json serialization."""
        return {
            "status": self.status.value,
            "healthy": self.status == HealthStatus.HEALTHY,
            "timestamp": self.timestamp.isoformat(),
            "components": {
                name: {
                    "healthy": c.healthy,
                    "message": c.message,
                    "error": c.error,
                    "last_check": c.last_check.isoformat(),
                    "details": c.details,
                }
                for name, c in self.components.items()
            },
        }


class HealthChecker:
    """
    health checker for agent infrastructure.

    registers health check functions for various components and
    provides a unified way to check overall system health.

    usage:
        checker = HealthChecker()

        # add checks
        checker.add_check("database", check_db_connection)
        checker.add_check("redis", check_redis_connection)

        # run checks
        report = await checker.run_checks()
        if report.status == HealthStatus.HEALTHY:
            print("all good!")
    """

    def __init__(self):
        self._checks: dict[str, Callable[[], Any]] = {}
        self._async_checks: dict[str, Callable[[], Any]] = {}

    def add_check(
        self,
        name: str,
        check_func: Callable[[], bool | dict[str, Any]],
        is_async: bool = False,
    ) -> None:
        """
        register a health check function.

        args:
            name: name of the component
            check_func: function that returns True, False, or a dict with details
                       for sync checks, or a coroutine for async
            is_async: whether the check function is async
        """
        if is_async:
            self._async_checks[name] = check_func
        else:
            self._checks[name] = check_func

    def remove_check(self, name: str) -> bool:
        """remove a health check."""
        removed = False
        if name in self._checks:
            del self._checks[name]
            removed = True
        if name in self._async_checks:
            del self._async_checks[name]
            removed = True
        return removed

    async def check_component(self, name: str) -> ComponentHealth:
        """run a single component check."""
        # try sync checks first
        if name in self._checks:
            try:
                result = self._checks[name]()
                return self._parse_check_result(name, result)
            except Exception as e:
                return ComponentHealth(
                    name=name,
                    healthy=False,
                    error=str(e),
                    message=f"check failed with exception: {type(e).__name__}",
                )

        # try async checks
        if name in self._async_checks:
            try:
                result = await self._async_checks[name]()
                return self._parse_check_result(name, result)
            except Exception as e:
                return ComponentHealth(
                    name=name,
                    healthy=False,
                    error=str(e),
                    message=f"check failed with exception: {type(e).__name__}",
                )

        # unknown component
        return ComponentHealth(
            name=name,
            healthy=False,
            error=f"no check registered for '{name}'",
            message="unknown component",
        )

    def _parse_check_result(self, name: str, result: Any) -> ComponentHealth:
        """parse the result of a health check."""
        if isinstance(result, bool):
            return ComponentHealth(
                name=name,
                healthy=result,
                message="ok" if result else "check failed",
            )
        elif isinstance(result, dict):
            return ComponentHealth(
                name=name,
                healthy=result.get("healthy", True),
                message=result.get("message", ""),
                error=result.get("error"),
                details=result.get("details", {}),
            )
        else:
            # assume truthy = healthy
            return ComponentHealth(
                name=name,
                healthy=bool(result),
                message=str(result) if result else "check returned falsy value",
            )

    async def run_checks(self) -> HealthReport:
        """run all health checks and return a report."""
        components: dict[str, ComponentHealth] = {}

        # run sync checks
        for name in self._checks:
            components[name] = await self.check_component(name)

        # run async checks (could parallelize these)
        for name in self._async_checks:
            components[name] = await self.check_component(name)

        # determine overall status
        if not components:
            status = HealthStatus.HEALTHY
        elif all(c.healthy for c in components.values()):
            status = HealthStatus.HEALTHY
        elif any(c.healthy for c in components.values()):
            status = HealthStatus.DEGRADED
        else:
            status = HealthStatus.UNHEALTHY

        return HealthReport(status=status, components=components)

    async def is_healthy(self) -> bool:
        """simple health check - returns True if all checks pass."""
        report = await self.run_checks()
        return report.status == HealthStatus.HEALTHY

    async def is_ready(self) -> bool:
        """readiness check - returns True if system is ready to serve."""
        # for now same as health, but could be different
        # (e.g. might be healthy but not ready during startup)
        return await self.is_healthy()


# common health check helpers


def check_storage_accessible(storage_path: str) -> dict[str, Any]:
    """check if storage directory is accessible."""
    from pathlib import Path

    path = Path(storage_path)
    try:
        exists = path.exists()
        if not exists:
            return {
                "healthy": False,
                "message": "storage path does not exist",
                "details": {"path": str(path)},
            }

        # try to write a test file
        test_file = path / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()

        return {
            "healthy": True,
            "message": "storage accessible",
            "details": {"path": str(path)},
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "message": "storage not accessible",
            "details": {"path": str(path)},
        }


async def check_runtime_responsive(runtime: Any) -> dict[str, Any]:
    """check if agent runtime is responsive."""
    try:
        if not runtime.is_running:
            return {
                "healthy": False,
                "message": "runtime not running",
            }

        # try to get stats
        stats = runtime.get_stats()

        return {
            "healthy": True,
            "message": "runtime responsive",
            "details": {
                "running": stats.get("running"),
                "entry_points": stats.get("entry_points", 0),
            },
        }
    except Exception as e:
        return {
            "healthy": False,
            "error": str(e),
            "message": "runtime not responsive",
        }
