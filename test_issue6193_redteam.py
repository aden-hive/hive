import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Add core to path
sys.path.insert(0, str(Path(__file__).resolve().parent / "core"))

from framework.runner.runner import AgentRunner
from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.runtime.event_bus import EventType

async def test_fail_fast_when_no_input():
    """Verify headless execution fails when no input_data provided."""
    print("[TEST 1] Fail-fast behavior when no input_data...")
    
    # Mock Graph and Goal
    graph = MagicMock(spec=GraphSpec)
    graph.description = "Test Graph"
    graph.id = "test-agent"
    graph.nodes = [MagicMock(client_facing=True)]
    graph.edges = []
    graph.entry_node = "test-node"
    graph.terminal_nodes = []
    
    goal = MagicMock(spec=Goal)
    goal.success_criteria = []
    goal.constraints = []
    goal.name = "Test Goal"
    goal.description = "Test Goal Description"
    goal.id = "test-goal"
    
    with patch("framework.runner.runner.run_preload_validation"):
        runner = AgentRunner(Path("."), graph, goal, interactive=False, skip_credential_validation=True)
    
        # Mock runtime
        mock_runtime = MagicMock()
        mock_runtime.start = AsyncMock()
        mock_runtime.get_entry_points = MagicMock(return_value=[])
        
        # Manually track subscriptions
        input_handlers = []
        def subscribe(event_types, handler):
            if EventType.CLIENT_INPUT_REQUESTED in event_types:
                input_handlers.append(handler)
            return "sub1"
        mock_runtime.subscribe_to_events = subscribe
        
        # Trigger and wait
        async def trigger_and_wait(*args, **kwargs):
            for handler in input_handlers:
                await handler(MagicMock(node_id="test-node"))
            return MagicMock()
        mock_runtime.trigger_and_wait = trigger_and_wait
        runner._agent_runtime = mock_runtime
        
        # Simulate run with no input
        with patch("sys.stdin.isatty", return_value=False):
            result = await runner.run(input_data={})
    
    if not result.success and "headless mode" in result.error:
        print("  [PASS] Agent correctly returned failure result without infinite loop!")
        return True
    else:
        print(f"  [FAIL] Expected failure result, got: {result}")
        return False

async def test_injects_json_when_input_exists():
    """Verify headless execution injects input_data correctly."""
    print("[TEST 2] JSON injection when input_data exists...")
    
    # Mock Graph and Goal
    graph = MagicMock(spec=GraphSpec)
    graph.description = "Test Graph"
    graph.id = "test-agent"
    graph.nodes = [MagicMock(client_facing=True)]
    graph.edges = []
    graph.entry_node = "test-node"
    graph.terminal_nodes = []
    
    goal = MagicMock(spec=Goal)
    goal.success_criteria = []
    goal.constraints = []
    goal.name = "Test Goal"
    goal.description = "Test Goal Description"
    goal.id = "test-goal"
    
    with patch("framework.runner.runner.run_preload_validation"):
        runner = AgentRunner(Path("."), graph, goal, interactive=False, skip_credential_validation=True)
    
        # Mock runtime
        mock_runtime = MagicMock()
        mock_runtime.start = AsyncMock()
        mock_runtime.get_entry_points = MagicMock(return_value=[])
        
        # Track subscriptions
        input_handlers = []
        def subscribe(event_types, handler):
            if EventType.CLIENT_INPUT_REQUESTED in event_types:
                input_handlers.append(handler)
            return "sub1"
        mock_runtime.subscribe_to_events = subscribe
        
        # Mock inject_input
        mock_runtime.inject_input = AsyncMock(return_value=True)
        
        # Mock trigger_and_wait
        async def trigger_and_wait(*args, **kwargs):
            for handler in input_handlers:
                await handler(MagicMock(node_id="test-node"))
            return MagicMock()
        mock_runtime.trigger_and_wait = trigger_and_wait
        
        runner._agent_runtime = mock_runtime
        
        input_data = {"file": "/tmp/data.csv", "format": "csv"}
        
        # Run with input
        with patch("sys.stdin.isatty", return_value=False):
            await runner.run(input_data=input_data)
    
    if mock_runtime.inject_input.called:
        print("  [PASS] Input handler was registered and inject_input called!")
        return True
    else:
        print("  [FAIL] Input handler not registered or inject_input not called")
        return False

async def main():
    print("=" * 60)
    print("RED TEAM: Issue #6193 Fix Verification")
    print("=" * 60)
    
    results = []
    
    result1 = await test_fail_fast_when_no_input()
    results.append(result1)
    
    result2 = await test_injects_json_when_input_exists()
    results.append(result2)
    
    print("=" * 60)
    if all(results):
        print("ALL RED TEAM TESTS PASSED -- Infinite loop is DEAD.")
    else:
        print("REDFLAG: Some tests failed. Fix needs revision.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
