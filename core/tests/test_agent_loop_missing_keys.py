import pytest
from framework.agent_loop.agent_loop import AgentLoop
from framework.agent_loop.internals.types import OutputAccumulator

@pytest.mark.asyncio
async def test_get_missing_output_keys_regular_outputs():
    accumulator = OutputAccumulator()
    await accumulator.set("found_key", "value")
    
    # Missing key "missing_key"
    missing = AgentLoop._get_missing_output_keys(
        None,
        accumulator, 
        output_keys=["found_key", "missing_key"]
    )
    assert missing == ["missing_key"]

@pytest.mark.asyncio
async def test_get_missing_output_keys_nullable_only_none_populated():
    accumulator = OutputAccumulator()
    
    # Output keys empty, all nullable outputs unset
    missing = AgentLoop._get_missing_output_keys(
        None,
        accumulator, 
        output_keys=[],
        nullable_keys=["null_1", "null_2"]
    )
    assert missing == ["null_1", "null_2"]

@pytest.mark.asyncio
async def test_get_missing_output_keys_nullable_only_one_populated():
    accumulator = OutputAccumulator()
    await accumulator.set("null_1", "value")
    
    # Output keys empty, one nullable output populated
    missing = AgentLoop._get_missing_output_keys(
        None,
        accumulator, 
        output_keys=[],
        nullable_keys=["null_1", "null_2"]
    )
    assert missing == []
