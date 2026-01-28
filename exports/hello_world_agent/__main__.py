import sys
import argparse
import json
import asyncio
from pathlib import Path
from framework.runner.runner import load_agent_export
from framework.graph.executor import GraphExecutor
from framework.runtime.core import Runtime
from .tools import greet

async def main_async():
    parser = argparse.ArgumentParser(description="Run the Hello World Agent")
    parser.add_argument("--name", default="World", help="Name to greet")
    args = parser.parse_args()

    # Load the agent definition
    agent_file = Path(__file__).parent / "agent.json"
    
    print(f"Loading agent from {agent_file}")
    
    with open(agent_file) as f:
        graph, goal = load_agent_export(f.read())
    
    # Initialize components
    runtime = Runtime(storage_path=Path("./agent_logs"))
    executor = GraphExecutor(runtime=runtime)
    
    # Register functions
    # The 'greeter' node in agent.json has function="greet"
    executor.register_function("greeter", greet)
    
    print(f"Running agent with input: name='{args.name}'")
    
    # Execute
    try:
        result = await executor.execute(graph=graph, goal=goal, input_data={"name": args.name})
        
        if result.success:
            print("\n✅ Execution Successful!")
            print(f"Output: {json.dumps(result.output, indent=2)}")
        else:
            print(f"\n❌ Execution Failed: {result.error}")
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
