"""
Tests for Agent Lifecycle Management.

Tests cover:
- AgentState enum and state transitions
- AgentRuntime lifecycle methods (start, stop, pause, resume, drain)
- HealthChecker liveness and readiness probes
- Signal handler behavior
- EventType lifecycle events
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from framework.runtime.agent_runtime import (
    AgentRuntime,
    AgentRuntimeConfig,
    AgentState,
)
from framework.runtime.event_bus import EventType
from framework.runtime.health import (
    HealthChecker,
    HealthStatus,
    create_health_checker,
)

# === FIXTURES ===


@pytest.fixture
def mock_graph():
    """Create a mock graph spec."""
    graph = MagicMock()
    graph.get_node = MagicMock(return_value=MagicMock())
    return graph


@pytest.fixture
def mock_goal():
    """Create a mock goal."""
    goal = MagicMock()
    goal.id = "test-goal"
    return goal


@pytest.fixture
def mock_storage(tmp_path):
    """Create a temporary storage path."""
    return tmp_path / "storage"


@pytest.fixture
def runtime_config():
    """Create a test runtime config."""
    return AgentRuntimeConfig(
        max_concurrent_executions=10,
        cache_ttl=1.0,
        batch_interval=0.01,
    )


# === AGENT STATE TESTS ===


class TestAgentState:
    """Tests for AgentState enum."""

    def test_all_states_exist(self):
        """Verify all expected states are defined."""
        expected_states = [
            "INITIALIZING",
            "READY",
            "RUNNING",
            "PAUSED",
            "DRAINING",
            "STOPPED",
            "ERROR",
        ]
        for state_name in expected_states:
            assert hasattr(AgentState, state_name)

    def test_state_values(self):
        """Verify state string values."""
        assert AgentState.INITIALIZING.value == "initializing"
        assert AgentState.READY.value == "ready"
        assert AgentState.RUNNING.value == "running"
        assert AgentState.PAUSED.value == "paused"
        assert AgentState.DRAINING.value == "draining"
        assert AgentState.STOPPED.value == "stopped"
        assert AgentState.ERROR.value == "error"

    def test_state_is_string_enum(self):
        """Verify AgentState is a string enum."""
        assert isinstance(AgentState.READY, str)
        assert AgentState.READY == "ready"

    def test_valid_transitions_defined(self):
        """Verify valid_transitions returns dict for all states."""
        transitions = AgentState.valid_transitions()
        assert isinstance(transitions, dict)
        for state in AgentState:
            assert state in transitions

    def test_initializing_can_transition_to_ready(self):
        """INITIALIZING can transition to READY."""
        assert AgentState.INITIALIZING.can_transition_to(AgentState.READY)

    def test_initializing_can_transition_to_error(self):
        """INITIALIZING can transition to ERROR."""
        assert AgentState.INITIALIZING.can_transition_to(AgentState.ERROR)

    def test_initializing_cannot_transition_to_running(self):
        """INITIALIZING cannot directly transition to RUNNING."""
        assert not AgentState.INITIALIZING.can_transition_to(AgentState.RUNNING)

    def test_ready_can_transition_to_running(self):
        """READY can transition to RUNNING."""
        assert AgentState.READY.can_transition_to(AgentState.RUNNING)

    def test_ready_can_transition_to_paused(self):
        """READY can transition to PAUSED."""
        assert AgentState.READY.can_transition_to(AgentState.PAUSED)

    def test_running_can_transition_to_paused(self):
        """RUNNING can transition to PAUSED."""
        assert AgentState.RUNNING.can_transition_to(AgentState.PAUSED)

    def test_paused_can_transition_to_ready(self):
        """PAUSED can transition back to READY."""
        assert AgentState.PAUSED.can_transition_to(AgentState.READY)

    def test_draining_can_only_transition_to_stopped_or_error(self):
        """DRAINING can only go to STOPPED or ERROR."""
        assert AgentState.DRAINING.can_transition_to(AgentState.STOPPED)
        assert AgentState.DRAINING.can_transition_to(AgentState.ERROR)
        assert not AgentState.DRAINING.can_transition_to(AgentState.READY)
        assert not AgentState.DRAINING.can_transition_to(AgentState.RUNNING)

    def test_stopped_can_restart(self):
        """STOPPED can transition to INITIALIZING (restart)."""
        assert AgentState.STOPPED.can_transition_to(AgentState.INITIALIZING)

    def test_error_can_recover(self):
        """ERROR can transition to STOPPED or INITIALIZING."""
        assert AgentState.ERROR.can_transition_to(AgentState.STOPPED)
        assert AgentState.ERROR.can_transition_to(AgentState.INITIALIZING)


# === EVENT TYPE TESTS ===


class TestEventType:
    """Tests for lifecycle EventTypes."""

    def test_agent_lifecycle_events_exist(self):
        """Verify all agent lifecycle events are defined."""
        lifecycle_events = [
            "AGENT_STARTING",
            "AGENT_READY",
            "AGENT_PAUSING",
            "AGENT_PAUSED",
            "AGENT_RESUMING",
            "AGENT_DRAINING",
            "AGENT_STOPPING",
            "AGENT_STOPPED",
            "AGENT_ERROR",
        ]
        for event_name in lifecycle_events:
            assert hasattr(EventType, event_name)

    def test_event_values(self):
        """Verify event string values."""
        assert EventType.AGENT_STARTING.value == "agent_starting"
        assert EventType.AGENT_READY.value == "agent_ready"
        assert EventType.AGENT_PAUSED.value == "agent_paused"
        assert EventType.AGENT_STOPPED.value == "agent_stopped"


# === AGENT RUNTIME LIFECYCLE TESTS ===


class TestAgentRuntimeLifecycle:
    """Tests for AgentRuntime lifecycle management."""

    @pytest.mark.asyncio
    async def test_initial_state_is_initializing(self, mock_graph, mock_goal, mock_storage):
        """Runtime starts in INITIALIZING state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        assert runtime.state == AgentState.INITIALIZING
        assert not runtime.is_running
        assert not runtime.is_paused
        assert not runtime.is_draining

    @pytest.mark.asyncio
    async def test_start_transitions_to_ready(self, mock_graph, mock_goal, mock_storage):
        """Starting runtime transitions to READY state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()

        assert runtime.state == AgentState.READY
        assert runtime.is_running
        assert runtime.started_at is not None
        assert runtime.uptime_seconds >= 0

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_stop_transitions_to_stopped(self, mock_graph, mock_goal, mock_storage):
        """Stopping runtime transitions to STOPPED state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.stop()

        assert runtime.state == AgentState.STOPPED
        assert not runtime.is_running

    @pytest.mark.asyncio
    async def test_pause_transitions_to_paused(self, mock_graph, mock_goal, mock_storage):
        """Pausing runtime transitions to PAUSED state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.pause()

        assert runtime.state == AgentState.PAUSED
        assert runtime.is_paused
        assert runtime.is_running  # Still running, just paused

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_resume_transitions_from_paused(self, mock_graph, mock_goal, mock_storage):
        """Resuming runtime transitions from PAUSED to READY."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.pause()
        await runtime.resume()

        assert runtime.state == AgentState.READY
        assert not runtime.is_paused

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_pause_not_running_raises(self, mock_graph, mock_goal, mock_storage):
        """Pausing when not running raises RuntimeError."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        with pytest.raises(RuntimeError, match="not running"):
            await runtime.pause()

    @pytest.mark.asyncio
    async def test_resume_not_paused_raises(self, mock_graph, mock_goal, mock_storage):
        """Resuming when not paused raises RuntimeError."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()

        with pytest.raises(RuntimeError, match="not paused"):
            await runtime.resume()

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_drain_transitions_to_draining(self, mock_graph, mock_goal, mock_storage):
        """Draining runtime transitions to DRAINING state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()

        # Drain should complete immediately with no active executions
        result = await runtime.drain(timeout_seconds=1.0)

        assert result is True  # Drain completed successfully
        assert not runtime.is_draining  # Draining finished

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_trigger_when_paused_raises(self, mock_graph, mock_goal, mock_storage):
        """Triggering execution when paused raises RuntimeError."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.pause()

        with pytest.raises(RuntimeError, match="paused"):
            await runtime.trigger("test", {})

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_trigger_when_draining_raises(self, mock_graph, mock_goal, mock_storage):
        """Triggering execution when draining raises RuntimeError."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()

        # Start drain in background
        async def drain_background():
            runtime._draining = True
            await asyncio.sleep(0.5)
            runtime._draining = False

        asyncio.create_task(drain_background())
        await asyncio.sleep(0.1)  # Let drain start

        with pytest.raises(RuntimeError, match="draining"):
            await runtime.trigger("test", {})

        await runtime.stop()


# === HEALTH CHECKER TESTS ===


class TestHealthChecker:
    """Tests for HealthChecker."""

    @pytest.mark.asyncio
    async def test_liveness_true_when_running(self, mock_graph, mock_goal, mock_storage):
        """Liveness returns True when runtime is running."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        health = HealthChecker(runtime)

        assert health.liveness() is True

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_liveness_true_when_stopped(self, mock_graph, mock_goal, mock_storage):
        """Liveness returns True when stopped (not in ERROR state)."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        health = HealthChecker(runtime)

        # Even when not running, liveness is True (not ERROR)
        assert health.liveness() is True

    @pytest.mark.asyncio
    async def test_liveness_false_when_error(self, mock_graph, mock_goal, mock_storage):
        """Liveness returns False when in ERROR state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        health = HealthChecker(runtime)

        # Simulate error state
        runtime._state = AgentState.ERROR

        assert health.liveness() is False

    @pytest.mark.asyncio
    async def test_readiness_true_when_ready(self, mock_graph, mock_goal, mock_storage):
        """Readiness returns True when in READY state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        health = HealthChecker(runtime)

        assert health.readiness() is True

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_readiness_false_when_paused(self, mock_graph, mock_goal, mock_storage):
        """Readiness returns False when paused."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.pause()
        health = HealthChecker(runtime)

        assert health.readiness() is False

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_readiness_false_when_draining(self, mock_graph, mock_goal, mock_storage):
        """Readiness returns False when draining."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        runtime._state = AgentState.DRAINING
        health = HealthChecker(runtime)

        assert health.readiness() is False

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_readiness_false_when_initializing(self, mock_graph, mock_goal, mock_storage):
        """Readiness returns False when initializing."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        health = HealthChecker(runtime)

        # Not started yet, still initializing
        assert health.readiness() is False

    @pytest.mark.asyncio
    async def test_health_returns_status(self, mock_graph, mock_goal, mock_storage):
        """Health returns comprehensive HealthStatus."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        health = HealthChecker(runtime)
        status = health.health()

        assert isinstance(status, HealthStatus)
        assert status.status == "healthy"
        assert status.state == "ready"
        assert status.uptime_seconds >= 0
        assert status.active_executions == 0
        assert status.started_at is not None
        assert len(status.dependencies) > 0

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_health_status_to_dict(self, mock_graph, mock_goal, mock_storage):
        """HealthStatus.to_dict returns JSON-serializable dict."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        health = HealthChecker(runtime)
        status = health.health()
        data = status.to_dict()

        assert isinstance(data, dict)
        assert "status" in data
        assert "state" in data
        assert "uptime_seconds" in data
        assert "dependencies" in data
        assert isinstance(data["dependencies"], list)

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_health_degraded_when_paused(self, mock_graph, mock_goal, mock_storage):
        """Health status is 'degraded' when paused."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.pause()
        health = HealthChecker(runtime)
        status = health.health()

        assert status.status == "degraded"

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_health_unhealthy_when_error(self, mock_graph, mock_goal, mock_storage):
        """Health status is 'unhealthy' when in ERROR state."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )
        runtime._state = AgentState.ERROR
        health = HealthChecker(runtime)
        status = health.health()

        assert status.status == "unhealthy"


class TestHealthCheckerFactory:
    """Tests for health checker factory function."""

    @pytest.mark.asyncio
    async def test_create_health_checker(self, mock_graph, mock_goal, mock_storage):
        """Factory creates a HealthChecker instance."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        health = create_health_checker(runtime)

        assert isinstance(health, HealthChecker)


# === STATS TESTS ===


class TestAgentRuntimeStats:
    """Tests for runtime statistics."""

    @pytest.mark.asyncio
    async def test_stats_include_lifecycle_info(self, mock_graph, mock_goal, mock_storage):
        """Runtime stats include lifecycle information."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        stats = runtime.get_stats()

        assert "state" in stats
        assert "paused" in stats
        assert "draining" in stats
        assert "uptime_seconds" in stats
        assert "active_executions" in stats

        assert stats["state"] == "ready"
        assert stats["paused"] is False
        assert stats["draining"] is False

        await runtime.stop()


# === GRACEFUL SHUTDOWN TESTS ===


class TestGracefulShutdown:
    """Tests for graceful shutdown behavior."""

    @pytest.mark.asyncio
    async def test_graceful_shutdown_drains_and_stops(
        self, mock_graph, mock_goal, mock_storage
    ):
        """Graceful shutdown drains then stops."""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=mock_storage,
        )

        await runtime.start()
        await runtime.graceful_shutdown(timeout_seconds=1.0)

        assert runtime.state == AgentState.STOPPED
        assert not runtime.is_running
