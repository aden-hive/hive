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

# Mock Agent for testing
async def run_agent(input_data):
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
        
        # Mock trigger_and_wait to simulate input request
        async def trigger_and_wait(*args, **kwargs):
            for handler in input_handlers:
                await handler(MagicMock(node_id="test-node"))
            return MagicMock()
        mock_runtime.trigger_and_wait = trigger_and_wait
        
        runner._agent_runtime = mock_runtime
        
        with patch("sys.stdin.isatty", return_value=False):
            return await runner.run(input_data=input_data)

async def test_cicd_simulation():
    print("\n[STRESS 5] CI/CD Pipeline simulation (result check)...")
    result = await run_agent(input_data={})
    
    if not result.success and "headless mode" in result.error:
        print("  [PASS] CI pipeline would get failure result")
        return True
    return False

async def test_user_error_message():
    print("\n[USER 1] Error message readability...")
    result = await run_agent(input_data={})
    
    output = result.error
    # We expect the error to be set by _handle_headless_input
    # The error message should be: "Agent requires interactive input but was run in headless mode. Provide input via --input-file or use interactive mode."
    
    checks = [
        ("interactive input" in output, "Mentions interactive input"),
        ("headless mode" in output, "Mentions headless mode"),
        ("Provide input" in output, "Suggests providing input"),
        ("interactive mode" in output, "Suggests alternative"),
    ]
    all_pass = True
    for check, desc in checks:
        print(f"  {'[PASS]' if check else '[FAIL]'} {desc}")
        if not check: all_pass = False
    return all_pass

async def main():
    print("=" * 70)
    print("STRESS TESTS + USER PERSPECTIVE TESTS: Issue #6193")
    print("=" * 70)
    
    results = [
        await test_cicd_simulation(),
        await test_user_error_message()
    ]
    
    print("\n" + "=" * 70)
    passed = sum(1 for r in results if r)
    print(f"RESULTS: {passed}/{len(results)} tests passed")
    if all(results):
        print("ALL STRESS + USER TESTS PASSED")
    else:
        print("REDFLAG: Tests failed.")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
