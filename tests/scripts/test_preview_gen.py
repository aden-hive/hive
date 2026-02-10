import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parents[2]))

# Ensure core is in path
sys.path.insert(0, str(Path(__file__).parents[2] / "core"))

from framework.builder.workflow import GraphBuilder
from framework.graph.goal import Goal, SuccessCriterion

async def test_preview_generation():
    print("Testing preview generation...")
    
    goal = Goal(
        id="test-goal",
        name="Test Agent",
        description="Create a simple agent that echoes input.",
        success_criteria=[
            SuccessCriterion(id="sc1", description="Echoes input", metric="output_equals", target="input")
        ]
    )
    
    builder = GraphBuilder(name="TestAgent")
    builder.set_goal(goal)
    
    print("Goal set. Generating preview...")
    # This might use the mock if no API key, which is fine for testing validity
    preview = await builder.generate_preview()
    
    print("Preview generated:")
    print(f"Goal Summary: {preview.goal_summary}")
    print(f"Nodes: {len(preview.proposed_nodes)}")
    print(f"Edges: {len(preview.proposed_edges)}")
    
    assert preview.goal_summary
    assert len(preview.proposed_nodes) > 0
    
    print("Test passed!")

if __name__ == "__main__":
    asyncio.run(test_preview_generation())
