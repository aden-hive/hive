import pytest
import asyncio
from core.safety.evolution_guard import EvolutionGuard

#--------------------------------------------------------------
# Mock Data 
#---------------------------------------------------------------
HEALTHY_GRAPH = {
    "nodes": ["Start", "Think", "Act"],
    "edges": [("Start", "Think"), ("Think", "Act")],
    "version": 1.0
}

BROKEN_GRAPH = {
    "nodes": ["Start", "Loop_A", "Loop_B"],
    "edges": [("Start", "Loop_A"), ("Loop_A", "Loop_B"), ("Loop_B", "Loop_A")], 
    "version": 2.0
}

# Fixture
@pytest.fixture
def guard():
    return EvolutionGuard()

async def mock_execution_engine(graph):
    """Simulates running the agent."""
    await asyncio.sleep(0.01)
    if "Loop_A" in graph["nodes"]:
        await asyncio.sleep(10) 
        return False
    return True

#------------------------------------------------------------------------
# Actual Tests
#------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_creation(guard):
    """Test 1: Does snapshotting work?"""
    snapshot_id = guard.snapshot(HEALTHY_GRAPH, reason="Unit Test")
    assert snapshot_id is not None
    assert guard._snapshots[snapshot_id].graph_state["version"] == 1.0

@pytest.mark.asyncio
async def test_probation_catch_failure(guard):
    """Test 2: Does it catch the infinite loop?"""
    snapshot_id = guard.snapshot(HEALTHY_GRAPH)
    
    result = await guard.probation_run(
        snapshot_id=snapshot_id,
        candidate_graph=BROKEN_GRAPH,
        test_function=mock_execution_engine,
        max_steps=5
    )

    assert result.success is False
    assert "Infinite Loop" in result.error_message

@pytest.mark.asyncio
async def test_rollback_integrity(guard):
    """Test 3: Does rollback give back the exact original?"""
    snapshot_id = guard.snapshot(HEALTHY_GRAPH)
    
    HEALTHY_GRAPH["version"] = 999.0 
    
    restored = guard.rollback(snapshot_id)
    
    assert restored["version"] == 1.0