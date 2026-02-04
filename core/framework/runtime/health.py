"""
Health Check Module - Kubernetes-compatible health probes for agent runtime.

Provides liveness and readiness probes for production deployments,
plus detailed health status for monitoring dashboards.

Usage:
    runtime = AgentRuntime(...)
    await runtime.start()

    health = HealthChecker(runtime)

    # Kubernetes liveness probe
    if health.liveness():
        return 200  # OK
    else:
        return 503  # Service Unavailable

    # Kubernetes readiness probe
    if health.readiness():
        return 200  # OK
    else:
        return 503  # Service Unavailable

    # Detailed health status
    status = health.health()
    print(f"Status: {status.status}, State: {status.state}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from framework.runtime.agent_runtime import AgentRuntime

logger = logging.getLogger(__name__)


# Health status values
HealthStatusType = Literal["healthy", "degraded", "unhealthy"]


@dataclass
class DependencyHealth:
    """Health status of a single dependency."""

    name: str
    healthy: bool
    message: str = ""
    latency_ms: float | None = None


@dataclass
class HealthStatus:
    """
    Comprehensive health status for the agent runtime.

    Used for detailed health endpoints and monitoring dashboards.
    """

    status: HealthStatusType
    state: str  # AgentState value
    uptime_seconds: float
    active_executions: int
    started_at: datetime | None = None
    last_execution_at: datetime | None = None
    dependencies: list[DependencyHealth] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status,
            "state": self.state,
            "uptime_seconds": self.uptime_seconds,
            "active_executions": self.active_executions,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_execution_at": (
                self.last_execution_at.isoformat() if self.last_execution_at else None
            ),
            "dependencies": [
                {
                    "name": d.name,
                    "healthy": d.healthy,
                    "message": d.message,
                    "latency_ms": d.latency_ms,
                }
                for d in self.dependencies
            ],
            "details": self.details,
        }


class HealthChecker:
    """
    Health checker for agent runtime.

    Provides Kubernetes-compatible liveness and readiness probes,
    plus detailed health status for monitoring.

    Liveness Probe:
        Returns True if the agent process is alive and not in an
        unrecoverable error state. Use for Kubernetes liveness probe
        to trigger pod restart on failure.

    Readiness Probe:
        Returns True if the agent is ready to accept new executions.
        Use for Kubernetes readiness probe to control traffic routing.

    Example:
        from framework.runtime.health import HealthChecker

        health = HealthChecker(runtime)

        # Simple probes
        is_alive = health.liveness()    # -> bool
        is_ready = health.readiness()   # -> bool

        # Detailed status
        status = health.health()        # -> HealthStatus
        print(status.to_dict())
    """

    def __init__(self, runtime: AgentRuntime):
        """
        Initialize health checker.

        Args:
            runtime: The AgentRuntime to check health of
        """
        self._runtime = runtime

    def liveness(self) -> bool:
        """
        Check if the agent is alive.

        Returns True unless the runtime is in an unrecoverable ERROR state.
        This is suitable for Kubernetes liveness probes.

        Returns:
            True if alive, False if in error state
        """
        # Import here to avoid circular imports
        from framework.runtime.agent_runtime import AgentState

        return self._runtime.state != AgentState.ERROR

    def readiness(self) -> bool:
        """
        Check if the agent is ready to accept new executions.

        Returns True only when the runtime can accept new work:
        - READY: Started but no active executions
        - RUNNING: Actively processing and accepting new work

        Returns False when:
        - INITIALIZING: Still starting up
        - PAUSED: Temporarily suspended
        - DRAINING: Finishing work, not accepting new
        - STOPPED: Fully stopped
        - ERROR: In error state

        This is suitable for Kubernetes readiness probes.

        Returns:
            True if ready to accept work, False otherwise
        """
        from framework.runtime.agent_runtime import AgentState

        return self._runtime.state in (AgentState.READY, AgentState.RUNNING)

    def health(self) -> HealthStatus:
        """
        Get detailed health status.

        Returns comprehensive health information including:
        - Overall status (healthy/degraded/unhealthy)
        - Current lifecycle state
        - Uptime and execution statistics
        - Dependency health (storage, LLM, etc.)

        Returns:
            HealthStatus with detailed information
        """
        from framework.runtime.agent_runtime import AgentState

        state = self._runtime.state
        stats = self._runtime.get_stats()

        # Determine overall status
        if state == AgentState.ERROR:
            status: HealthStatusType = "unhealthy"
        elif state in (AgentState.PAUSED, AgentState.DRAINING):
            status = "degraded"
        else:
            status = "healthy"

        # Check dependencies
        dependencies = self._check_dependencies()

        # If any critical dependency is unhealthy, degrade status
        if any(not d.healthy for d in dependencies):
            if status == "healthy":
                status = "degraded"

        return HealthStatus(
            status=status,
            state=state.value,
            uptime_seconds=self._runtime.uptime_seconds,
            active_executions=stats.get("active_executions", 0),
            started_at=self._runtime.started_at,
            last_execution_at=None,  # TODO: Track last execution time
            dependencies=dependencies,
            details={
                "entry_points": stats.get("entry_points", 0),
                "paused": stats.get("paused", False),
                "draining": stats.get("draining", False),
            },
        )

    def _check_dependencies(self) -> list[DependencyHealth]:
        """
        Check health of runtime dependencies.

        Returns:
            List of dependency health statuses
        """
        dependencies = []

        # Check if runtime is running (storage is active)
        storage_healthy = self._runtime.is_running
        dependencies.append(
            DependencyHealth(
                name="storage",
                healthy=storage_healthy,
                message="Storage active" if storage_healthy else "Storage not started",
            )
        )

        # Check event bus
        try:
            event_bus_stats = self._runtime.event_bus.get_stats()
            dependencies.append(
                DependencyHealth(
                    name="event_bus",
                    healthy=True,
                    message=f"{event_bus_stats.get('subscriptions', 0)} subscriptions",
                )
            )
        except Exception as e:
            dependencies.append(
                DependencyHealth(
                    name="event_bus",
                    healthy=False,
                    message=str(e),
                )
            )

        # Check LLM provider if configured
        llm_health = self._check_llm_provider()
        if llm_health:
            dependencies.append(llm_health)

        return dependencies

    def _check_llm_provider(self) -> DependencyHealth | None:
        """
        Check health of the LLM provider.

        Returns:
            DependencyHealth for LLM, or None if no LLM configured
        """
        # Access the private _llm attribute safely
        llm = getattr(self._runtime, "_llm", None)

        if llm is None:
            return None

        try:
            # Check if LLM provider has a model attribute (basic sanity check)
            model = getattr(llm, "model", None) or getattr(llm, "_model", None)
            model_name = model if isinstance(model, str) else "configured"

            return DependencyHealth(
                name="llm_provider",
                healthy=True,
                message=f"LLM provider ready ({model_name})",
            )
        except Exception as e:
            return DependencyHealth(
                name="llm_provider",
                healthy=False,
                message=f"LLM provider error: {e}",
            )


def create_health_checker(runtime: AgentRuntime) -> HealthChecker:
    """
    Factory function to create a health checker.

    Args:
        runtime: The AgentRuntime to check

    Returns:
        Configured HealthChecker instance
    """
    return HealthChecker(runtime)
