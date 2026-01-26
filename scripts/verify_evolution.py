
import asyncio
import os
import shutil
from typing import List, Dict, Any
from framework.memory.hub import MemoryHub
from framework.memory.providers.local import LocalJSONLProvider
from framework.memory.provider import BaseEmbeddingProvider
from framework.memory.nodes.evolution_node import DynamicEvolutionNode
from framework.graph.node import NodeContext, NodeResult
from framework.graph.mutation import GraphDelta

# Mock Runtime Stub
class MockRuntime:
    def __init__(self, hub):
        self.memory_hub = hub
        
    async def apply_mutation(self, delta):
        print(f"MockRuntime: Applying mutation - {delta.reason}")
        return True

class MockEmbedder(BaseEmbeddingProvider):
    async def embed(self, text: str) -> List[float]:
        return [1.0]

async def main():
    test_file = "test_evolution.jsonl"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    embedder = MockEmbedder()
    provider = LocalJSONLProvider(file_path=test_file)
    hub = MemoryHub(provider, embedder)
    runtime = MockRuntime(hub)
    
    # 1. Seed Memory with Failures
    print("Seeding memory with failures...")
    for i in range(4):
        await hub.remember(f"Scraping failed timeout {i}", {}, outcome="failure")
    await hub.remember("Scraping worked once with proxy", {}, outcome="success")
    
    # 2. Run Evolution Node
    print("Running DynamicEvolutionNode...")
    node = DynamicEvolutionNode(failure_threshold=0.5)
    from framework.graph.node import NodeContext, NodeResult, NodeSpec, SharedMemory

    # Mock Spec
    spec = NodeSpec(id="evo_1", name="Evolution Node", description="Test", node_type="function")
    memory = SharedMemory()

    ctx = NodeContext(
        node_id="evo_1",
        node_spec=spec,
        runtime=runtime,
        input_data={"goal": "scraping data"},
        memory=memory,
        # history=[], # Removed
        # tracker=None # Removed
    )
    
    result = await node.execute(ctx)
    
    # 3. Verify Trigger
    print("Result Success:", result.success)
    print("Output:", result.output)
    
    if result.success:
        print(f"DEBUG: Logic failed to trigger. Failure rate: {result.output.get('failure_rate')}")
    
    # In my impl I set success=False to signal "stop standard flow".
    assert result.success == False 
    
    assert result.output["trigger_evolution"] == True
    assert "High failure rate" in result.output["reason"]
    
    # 4. Mock Mutation Application
    if result.output["trigger_evolution"]:
        delta = GraphDelta(
            reason=result.output["reason"],
            nodes_to_add=[], # Mock
            edges_to_add={}
        )
        await runtime.apply_mutation(delta)

    print("\nPASS: Evolution Logic Verified!")

    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(main())
