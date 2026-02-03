"""
tests for agent runtime error handling improvements.

tests the new warning logs, cleanup behavior, and health checks
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.execution_stream import EntryPointSpec


@pytest.fixture
def mock_goal():
    """create a mock goal for testing"""
    return Goal(
        id="test-goal",
        name="test goal",
        description="a goal for testing",
    )


@pytest.fixture
def mock_graph():
    """create a mock graph for testing"""
    graph = MagicMock(spec=GraphSpec)
    graph.get_node = MagicMock(return_value=MagicMock())  # pretend nodes exist
    return graph


@pytest.fixture
def tmp_storage_path(tmp_path):
    """get a temp path for storage"""
    return tmp_path / "storage"


class TestStartWarning:
    """test that start() logs warning when already running"""

    @pytest.mark.asyncio
    async def test_double_start_logs_warning(self, mock_goal, mock_graph, tmp_storage_path, caplog):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        # first start should work
        await runtime.start()
        assert runtime.is_running

        # second start should log warning
        with caplog.at_level("WARNING"):
            await runtime.start()

        assert "already running" in caplog.text.lower()

        await runtime.stop()

    @pytest.mark.asyncio
    async def test_double_stop_logs_debug(self, mock_goal, mock_graph, tmp_storage_path, caplog):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        await runtime.start()
        await runtime.stop()

        # second stop should log debug
        with caplog.at_level("DEBUG"):
            await runtime.stop()

        assert "not running" in caplog.text.lower()


class TestHealthCheck:
    """test the health check method"""

    @pytest.mark.asyncio
    async def test_health_check_when_not_running(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        # not started, should be unhealthy
        health = await runtime.health_check()
        assert health["healthy"] is False
        assert health["status"] == "not_running"

    @pytest.mark.asyncio
    async def test_health_check_when_running(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        await runtime.start()

        try:
            health = await runtime.health_check()
            assert health["healthy"] is True
            assert health["status"] == "healthy"
            assert "components" in health
            assert "runtime" in health["components"]
            assert health["components"]["runtime"]["healthy"] is True
        finally:
            await runtime.stop()

    @pytest.mark.asyncio
    async def test_health_check_with_streams(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        # register an entry point
        runtime.register_entry_point(
            EntryPointSpec(
                id="test-ep",
                name="Test Entry Point",
                entry_node="some-node",
                trigger_type="webhook",
            )
        )

        await runtime.start()

        try:
            health = await runtime.health_check()
            assert health["healthy"] is True
            # should have stream component
            assert "stream_test-ep" in health["components"]
        finally:
            await runtime.stop()


class TestCleanupOnError:
    """test cleanup behavior when errors occur"""

    @pytest.mark.asyncio
    async def test_streams_cleaned_up_on_stop_error(
        self, mock_goal, mock_graph, tmp_storage_path, caplog
    ):
        """if a stream fails to stop, others should still be stopped"""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        await runtime.start()

        # manually inject a broken stream that will fail on stop
        mock_broken_stream = MagicMock()
        mock_broken_stream.stop = AsyncMock(side_effect=Exception("stop failed"))
        mock_broken_stream.get_stats = MagicMock(return_value={})
        runtime._streams["broken"] = mock_broken_stream

        # stop should still complete
        with caplog.at_level("ERROR"):
            await runtime.stop()

        assert not runtime.is_running
        assert "failed to stop stream" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_storage_cleanup_error_logged(
        self, mock_goal, mock_graph, tmp_storage_path, caplog
    ):
        """if storage fails to stop, it should be logged"""
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        await runtime.start()

        # mock storage to fail on stop
        runtime._storage.stop = AsyncMock(side_effect=Exception("storage stop failed"))

        with caplog.at_level("ERROR"):
            await runtime.stop()

        assert not runtime.is_running
        assert "failed to stop storage" in caplog.text.lower()


class TestEntryPointValidation:
    """test entry point registration validation"""

    def test_cant_register_when_running(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        # manually set running (hack for testing)
        runtime._running = True

        with pytest.raises(RuntimeError) as exc:
            runtime.register_entry_point(
                EntryPointSpec(
                    id="test",
                    name="test",
                    entry_node="node",
                    trigger_type="webhook",
                )
            )

        assert "running" in str(exc.value).lower()

    def test_duplicate_entry_point_rejected(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        spec = EntryPointSpec(
            id="test",
            name="test",
            entry_node="node",
            trigger_type="webhook",
        )

        runtime.register_entry_point(spec)

        with pytest.raises(ValueError) as exc:
            runtime.register_entry_point(spec)

        assert "already registered" in str(exc.value).lower()

    def test_invalid_entry_node_rejected(self, mock_goal, mock_graph, tmp_storage_path):
        mock_graph.get_node = MagicMock(return_value=None)  # node doesnt exist

        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        with pytest.raises(ValueError) as exc:
            runtime.register_entry_point(
                EntryPointSpec(
                    id="test",
                    name="test",
                    entry_node="nonexistent-node",
                    trigger_type="webhook",
                )
            )

        assert "not found" in str(exc.value).lower()


class TestTriggerValidation:
    """test trigger method validation"""

    @pytest.mark.asyncio
    async def test_trigger_when_not_running(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        with pytest.raises(RuntimeError) as exc:
            await runtime.trigger("test", {})

        assert "not running" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_trigger_invalid_entry_point(self, mock_goal, mock_graph, tmp_storage_path):
        runtime = AgentRuntime(
            graph=mock_graph,
            goal=mock_goal,
            storage_path=tmp_storage_path,
        )

        await runtime.start()

        try:
            with pytest.raises(ValueError) as exc:
                await runtime.trigger("nonexistent", {})

            assert "not found" in str(exc.value).lower()
        finally:
            await runtime.stop()
