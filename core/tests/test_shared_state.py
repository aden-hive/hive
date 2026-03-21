import asyncio

import pytest

from framework.runtime.shared_state import (
    IsolationLevel,
    SharedStateManager,
    StateScope,
)


@pytest.mark.asyncio
async def test_atomic_update_concurrency():
    """
    Verifies that atomic_update correctly handles concurrent increments
    without data loss (fixing the TOCTOU race condition).
    """
    manager = SharedStateManager()
    key = "shared_counter"
    num_agents = 10
    increments_per_agent = 50
    expected_total = num_agents * increments_per_agent
    stream_id = "test_stream"

    async def agent_task(agent_id):
        memory = manager.create_memory(
            execution_id=f"exec_{agent_id}",
            stream_id=stream_id,
            isolation=IsolationLevel.SYNCHRONIZED,
        )
        for _ in range(increments_per_agent):
            # Using the new atomic_update method
            await memory.atomic_update(
                key, lambda v: (v or 0) + 1, scope=StateScope.STREAM
            )
            # Yield to other tasks to maximize race opportunity
            await asyncio.sleep(0)

    # Run agents concurrently
    tasks = [agent_task(i) for i in range(num_agents)]
    await asyncio.gather(*tasks)

    # Verify final value
    final_val = await manager.read(
        key,
        execution_id="check",
        stream_id=stream_id,
        isolation=IsolationLevel.SYNCHRONIZED,
    )

    assert final_val == expected_total


@pytest.mark.asyncio
async def test_atomic_update_isolated_scope():
    """Verifies atomic_update still works for ISOLATED/EXECUTION scope."""
    manager = SharedStateManager()
    memory = manager.create_memory("exec_1", "stream_1", IsolationLevel.ISOLATED)

    await memory.atomic_update("count", lambda v: (v or 0) + 1)
    await memory.atomic_update("count", lambda v: (v or 0) + 1)

    assert await memory.read("count") == 2
