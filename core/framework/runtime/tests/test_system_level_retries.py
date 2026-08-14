import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from framework.orchestrator.node import NodeProtocol, NodeContext, NodeResult, NodeSpec, DataBuffer
from framework.orchestrator.node_worker import NodeWorker, WorkerLifecycle
from framework.orchestrator.context import GraphContext
from framework.orchestrator.edge import GraphSpec

class FlakySystemNode(NodeProtocol):
    """A mock node that simulates a transient infrastructure crash before succeeding."""
    def __init__(self):
        self.attempts = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempts += 1
        if self.attempts < 3:
            # Simulate a raw system exception (e.g., DB connection dropped)
            raise ConnectionError("Simulated transient network drop.")
        
        return NodeResult(success=True, output={"status": "recovered"})

class CancelledNode(NodeProtocol):
    """A mock node that simulates a system interruption."""
    async def execute(self, ctx: NodeContext) -> NodeResult:
        raise asyncio.CancelledError("Simulated system interrupt.")

@pytest.mark.asyncio
async def test_worker_catches_raw_exception_and_retries():
    """Verify that a raw exception is caught and triggers the retry loop."""
    
    node_spec = NodeSpec(
        id="test_flaky_node", 
        name="Flaky Node", 
        description="Tests retries", 
        max_retries=3
    )
    
    mock_graph = GraphSpec(id="test_graph", goal_id="test_goal", entry_node="test_flaky_node", nodes=[node_spec], edges=[])
    
    # Mocking GraphContext to bypass deep instantiation
    mock_gc = MagicMock(spec=GraphContext)
    mock_gc.graph = mock_graph
    mock_gc.retry_counts = {}
    mock_gc.nodes_with_retries = set()
    mock_gc.is_continuous = False
    mock_gc._visits_lock = asyncio.Lock()
    mock_gc._path_lock = asyncio.Lock()
    mock_gc.node_visit_counts = {}
    mock_gc.path = []
    mock_gc.buffer = MagicMock(spec=DataBuffer)
    mock_gc.event_bus = None
    
    worker = NodeWorker(node_spec=node_spec, graph_context=mock_gc)
    worker._node_impl = FlakySystemNode()
    
    # Mock out internal methods that would try to touch the real event bus/edges
    worker._build_node_context = MagicMock(return_value=MagicMock(spec=NodeContext))
    worker._evaluate_outgoing_edges = AsyncMock(return_value=[])
    worker._publish_completion = AsyncMock()
    worker._publish_failure = AsyncMock()
    
    await worker._execute_self()
    
    assert worker.lifecycle == WorkerLifecycle.COMPLETED
    assert worker._node_impl.attempts == 3
    assert mock_gc.retry_counts["test_flaky_node"] == 2
    assert worker._last_result is not None
    assert worker._last_result.success is True

@pytest.mark.asyncio
async def test_worker_respects_asyncio_cancelled_error():
    """Verify that asyncio.CancelledError is NOT swallowed by the broad exception handler."""
    
    node_spec = NodeSpec(
        id="test_cancel_node", 
        name="Cancel Node", 
        description="Tests cancellation", 
        max_retries=3
    )
    
    mock_gc = MagicMock(spec=GraphContext)
    # Added goal_id="test_goal" to satisfy Pydantic
    mock_gc.graph = GraphSpec(id="test_graph", goal_id="test_goal", entry_node="test_cancel_node", nodes=[node_spec], edges=[])
    mock_gc._visits_lock = asyncio.Lock()
    mock_gc._path_lock = asyncio.Lock()
    mock_gc.node_visit_counts = {}
    mock_gc.path = []
    mock_gc.buffer = MagicMock(spec=DataBuffer)
    mock_gc.event_bus = None
    
    worker = NodeWorker(node_spec=node_spec, graph_context=mock_gc)
    worker._node_impl = CancelledNode()
    worker._build_node_context = MagicMock(return_value=MagicMock(spec=NodeContext))
    
    # The CancelledError should bubble up completely, bypassing the retry loop
    with pytest.raises(asyncio.CancelledError):
        await worker._execute_self()