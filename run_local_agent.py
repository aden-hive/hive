import asyncio
import sys
from pathlib import Path

# Add paths for imports
hive_path = Path(__file__).parent
sys.path.insert(0, str(hive_path / "core"))
sys.path.insert(0, str(hive_path / "exports"))

from local_agent.graph import build_graph
from framework.graph.goal import Goal
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime
from framework.storage.backend import FileStorage

async def main():
    """Run the local agent with a simple echo test."""
    try:
        # Build the graph
        graph = build_graph()
        
        # Create runtime and storage
        storage = FileStorage("/tmp/agent_runs")
        runtime = Runtime(storage=storage)
        
        # Create goal
        goal = Goal(
            id="echo_goal",
            name="Echo Test",
            description="Test the echo response node",
        )
        
        # Create executor
        executor = GraphExecutor(runtime=runtime)
        
        # Execute the graph
        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"input": "Explain AI agents simply"},
        )
        
        # Print results
        if result.success:
            print("✓ Execution successful!")
            print(f"Output: {result.output}")
        else:
            print(f"✗ Execution failed: {result.error}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
