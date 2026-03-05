"""
Tests for OrchestrationMemory - cross-agent memory sharing.
"""

import asyncio
import pytest

from framework.runtime.orchestration_memory import (
    OrchestrationMemory,
    OrchestrationScope,
    SharedData,
)


class TestOrchestrationMemoryBasic:
    """Test basic share and read operations."""

    @pytest.fixture
    def memory(self):
        """Create a fresh OrchestrationMemory instance."""
        return OrchestrationMemory(workflow_id="test-workflow-001")

    @pytest.mark.asyncio
    async def test_share_and_read(self, memory):
        """Test basic share and read operations."""
        # Agent A shares data
        await memory.share(
            key="search_results",
            value=["result1", "result2"],
            from_agent="search_agent",
        )

        # Read back the data
        result = await memory.read_shared(
            key="search_results",
            from_agent="search_agent",
        )

        assert result == ["result1", "result2"]

    @pytest.mark.asyncio
    async def test_read_shared_default(self, memory):
        """Test that read_shared returns default when key not found."""
        result = await memory.read_shared(
            key="nonexistent",
            default="fallback",
        )
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_read_without_agent_filter(self, memory):
        """Test reading without specifying from_agent."""
        await memory.share(
            key="data",
            value="agent_a_data",
            from_agent="agent_a",
        )

        # Should find the data without specifying agent
        result = await memory.read_shared(key="data")
        assert result == "agent_a_data"

    @pytest.mark.asyncio
    async def test_read_all_from_agent(self, memory):
        """Test reading all data from a specific agent."""
        await memory.share(key="key1", value="val1", from_agent="agent_x")
        await memory.share(key="key2", value="val2", from_agent="agent_x")
        await memory.share(key="key3", value="val3", from_agent="agent_y")

        agent_x_data = await memory.read_all_from_agent("agent_x")
        assert agent_x_data == {"key1": "val1", "key2": "val2"}

        agent_y_data = await memory.read_all_from_agent("agent_y")
        assert agent_y_data == {"key3": "val3"}

    @pytest.mark.asyncio
    async def test_read_shared_sync(self, memory):
        """Test synchronous read operation."""
        # Share data using async
        await memory.share(key="sync_key", value="sync_value", from_agent="agent")

        # Read synchronously (this is the sync method we're testing)
        result = memory.read_shared_sync(key="sync_key", from_agent="agent")
        assert result == "sync_value"


class TestOrchestrationMemoryWorkflowIsolation:
    """Test that workflows are isolated from each other."""

    @pytest.mark.asyncio
    async def test_workflow_isolation(self):
        """Test that different workflows have isolated memory."""
        memory_a = OrchestrationMemory(workflow_id="workflow-a")
        memory_b = OrchestrationMemory(workflow_id="workflow-b")

        await memory_a.share(key="data", value="workflow_a_data", from_agent="agent1")
        await memory_b.share(key="data", value="workflow_b_data", from_agent="agent1")

        # Each should only see its own data
        result_a = await memory_a.read_shared(key="data", from_agent="agent1")
        result_b = await memory_b.read_shared(key="data", from_agent="agent1")

        assert result_a == "workflow_a_data"
        assert result_b == "workflow_b_data"

    @pytest.mark.asyncio
    async def test_workflow_id_property(self):
        """Test workflow_id property."""
        memory = OrchestrationMemory(workflow_id="my-workflow-123")
        assert memory.workflow_id == "my-workflow-123"


class TestOrchestrationMemoryAggregation:
    """Test aggregation of data from multiple agents."""

    @pytest.fixture
    def memory(self):
        return OrchestrationMemory(workflow_id="agg-workflow")

    @pytest.mark.asyncio
    async def test_aggregate_list(self, memory):
        """Test aggregating values as list."""
        await memory.share(key="score", value=85, from_agent="agent1")
        await memory.share(key="score", value=90, from_agent="agent2")
        await memory.share(key="score", value=75, from_agent="agent3")

        scores = await memory.aggregate(key="score", strategy="list")
        assert sorted(scores) == [75, 85, 90]

    @pytest.mark.asyncio
    async def test_aggregate_dict(self, memory):
        """Test aggregating values as dict."""
        await memory.share(key="result", value="A", from_agent="agent1")
        await memory.share(key="result", value="B", from_agent="agent2")

        results = await memory.aggregate(key="result", strategy="dict")
        assert results == {"agent1": "A", "agent2": "B"}

    @pytest.mark.asyncio
    async def test_aggregate_first(self, memory):
        """Test getting first value."""
        await memory.share(key="first_key", value="first", from_agent="agent1")
        await memory.share(key="first_key", value="second", from_agent="agent2")

        result = await memory.aggregate(key="first_key", strategy="first")
        assert result in ["first", "second"]  # Order may vary

    @pytest.mark.asyncio
    async def test_aggregate_last(self, memory):
        """Test getting most recent value."""
        await memory.share(key="last_key", value="old", from_agent="agent1")
        await asyncio.sleep(0.01)  # Small delay to ensure timestamp difference
        await memory.share(key="last_key", value="new", from_agent="agent2")

        result = await memory.aggregate(key="last_key", strategy="last")
        assert result == "new"

    @pytest.mark.asyncio
    async def test_get_workflow_state(self, memory):
        """Test getting unified workflow state."""
        await memory.share(key="search", value="results", from_agent="searcher")
        await memory.share(key="summary", value="text", from_agent="summarizer")
        await memory.share(key="rank", value=5, from_agent="ranker")

        state = memory.get_workflow_state()

        assert state["searcher"] == {"search": "results"}
        assert state["summarizer"] == {"summary": "text"}
        assert state["ranker"] == {"rank": 5}


class TestOrchestrationMemoryAgentGroups:
    """Test agent group functionality."""

    @pytest.fixture
    def memory(self):
        return OrchestrationMemory(workflow_id="group-workflow")

    @pytest.mark.asyncio
    async def test_add_to_group_and_get_state(self, memory):
        """Test grouping agents and getting group state."""
        # Setup groups
        memory.add_to_group("researchers", "agent_a")
        memory.add_to_group("researchers", "agent_b")
        memory.add_to_group("writers", "agent_c")

        # Share data
        await memory.share(key="finding", value="data1", from_agent="agent_a")
        await memory.share(key="finding", value="data2", from_agent="agent_b")
        await memory.share(key="draft", value="text", from_agent="agent_c")

        # Get group state
        researcher_state = memory.get_group_state("researchers")
        assert "agent_a" in researcher_state
        assert "agent_b" in researcher_state
        assert "agent_c" not in researcher_state

        writer_state = memory.get_group_state("writers")
        assert "agent_c" in writer_state

    def test_get_empty_group(self, memory):
        """Test getting state for non-existent group."""
        result = memory.get_group_state("nonexistent")
        assert result == {}


class TestOrchestrationMemorySubscriptions:
    """Test subscription/notification functionality."""

    @pytest.fixture
    def memory(self):
        return OrchestrationMemory(workflow_id="sub-workflow")

    @pytest.mark.asyncio
    async def test_subscribe_to_key(self, memory):
        """Test subscribing to key updates."""
        received = []

        def handler(data: SharedData):
            received.append(data)

        memory.subscribe("test_key", handler)

        await memory.share(key="test_key", value="value1", from_agent="agent1")

        assert len(received) == 1
        assert received[0].key == "test_key"
        assert received[0].value == "value1"
        assert received[0].from_agent == "agent1"

    @pytest.mark.asyncio
    async def test_async_subscription_handler(self, memory):
        """Test async subscription handlers."""
        received = []

        async def async_handler(data: SharedData):
            await asyncio.sleep(0.01)
            received.append(data.value)

        memory.subscribe("async_key", async_handler)

        await memory.share(key="async_key", value="async_val", from_agent="agent")

        assert received == ["async_val"]

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, memory):
        """Test multiple subscribers on same key."""
        calls_a = []
        calls_b = []

        memory.subscribe("multi_key", lambda d: calls_a.append(d.value))
        memory.subscribe("multi_key", lambda d: calls_b.append(d.value))

        await memory.share(key="multi_key", value="shared", from_agent="agent")

        assert calls_a == ["shared"]
        assert calls_b == ["shared"]


class TestOrchestrationMemoryCleanup:
    """Test cleanup and resource management."""

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test that cleanup releases all resources."""
        memory = OrchestrationMemory(workflow_id="cleanup-workflow")

        await memory.share(key="data", value="value", from_agent="agent")
        memory.add_to_group("group", "agent")
        memory.subscribe("data", lambda d: None)

        stats_before = memory.get_stats()
        assert stats_before["total_keys"] > 0

        await memory.cleanup()

        stats_after = memory.get_stats()
        assert stats_after["total_keys"] == 0
        assert stats_after["contributing_agents"] == 0
        assert stats_after["agent_groups"] == 0
        assert stats_after["total_subscriptions"] == 0


class TestOrchestrationMemoryStats:
    """Test statistics and monitoring."""

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting memory statistics."""
        memory = OrchestrationMemory(workflow_id="stats-workflow")

        await memory.share(key="k1", value="v1", from_agent="a1")
        await memory.share(key="k2", value="v2", from_agent="a2")
        memory.add_to_group("g1", "a1")
        memory.subscribe("k1", lambda d: None)

        stats = memory.get_stats()

        assert stats["workflow_id"] == "stats-workflow"
        assert stats["total_keys"] == 2
        assert stats["contributing_agents"] == 2
        assert stats["agent_groups"] == 1
        assert stats["total_subscriptions"] == 1

    @pytest.mark.asyncio
    async def test_get_contributing_agents(self):
        """Test getting list of contributing agents."""
        memory = OrchestrationMemory(workflow_id="contrib-workflow")

        await memory.share(key="d1", value="v1", from_agent="agent_x")
        await memory.share(key="d2", value="v2", from_agent="agent_y")

        agents = memory.get_contributing_agents()
        assert sorted(agents) == ["agent_x", "agent_y"]

    @pytest.mark.asyncio
    async def test_get_history(self):
        """Test getting data sharing history."""
        memory = OrchestrationMemory(workflow_id="history-workflow")

        await memory.share(key="h1", value="v1", from_agent="a1")
        await memory.share(key="h2", value="v2", from_agent="a2")
        await memory.share(key="h3", value="v3", from_agent="a3")

        history = memory.get_history(limit=2)
        assert len(history) == 2
        # Should be last 2 entries
        assert history[0].key == "h2"
        assert history[1].key == "h3"


class TestOrchestrationMemoryScopes:
    """Test different orchestration scopes."""

    @pytest.mark.asyncio
    async def test_workflow_scope(self):
        """Test sharing with WORKFLOW scope."""
        memory = OrchestrationMemory(workflow_id="scope-workflow")

        await memory.share(
            key="workflow_data",
            value="shared",
            from_agent="agent",
            scope=OrchestrationScope.WORKFLOW,
        )

        # Verify scope is stored
        shared_data = memory._workflow_state.get(
            memory._make_key("agent", "workflow_data")
        )
        assert shared_data.scope == OrchestrationScope.WORKFLOW

    @pytest.mark.asyncio
    async def test_metadata(self):
        """Test sharing with metadata."""
        memory = OrchestrationMemory(workflow_id="meta-workflow")

        await memory.share(
            key="data",
            value="value",
            from_agent="agent",
            metadata={"source": "api", "priority": "high"},
        )

        shared_data = memory._workflow_state.get(memory._make_key("agent", "data"))
        assert shared_data.metadata == {"source": "api", "priority": "high"}
