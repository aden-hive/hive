import asyncio
import sys
from pathlib import Path

# Bootstrap path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "core"))

from framework.memory.nodes.memory_node import MemoryRecallNode
from framework.memory.hub import MemoryHub
from framework.memory.providers.local import LocalJSONLProvider
from framework.memory.provider import BaseEmbeddingProvider

class MockEmbedder(BaseEmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]

class MockRuntime:
    def __init__(self):
        self.memory_hub = MemoryHub(LocalJSONLProvider("test_integ.jsonl"), MockEmbedder())

async def main():
    print("🔌 Testing Memory Node Integration...")
    
    runtime = MockRuntime()
    # Pre-populate memory
    await runtime.memory_hub.remember("Deployment failed due to SSL error", {"type": "error"})
    
    node = MemoryRecallNode()
    
    # Mock Context
    class MockMemory:
        def __init__(self): self.data = {}
        def write(self, k, v): self.data[k] = v
        def read(self, k): return self.data.get(k)
        
    class MockContext:
        def __init__(self, runtime, input_data):
            self.runtime = runtime
            self.input_data = input_data
            self.memory = MockMemory()
            self.goal_context = ""
    
    # Test Input
    ctx_data = {"goal": "Fix SSL deployment"}
    mock_ctx = MockContext(runtime, ctx_data)
    
    print(f"Input: {ctx_data}")
    result = await node.execute(mock_ctx)
    
    print(f"Output: {result.output}")
    
    if result.success and result.output.get("historical_context"):
        print(f"Context Found: {result.output['historical_context']}")
        if "SSL error" in result.output['historical_context']:
             print("✅ Node successfully injected memory!")
        else:
             print("❌ Node failed to find relevant memory (or embedding mismatch)")
    else:
        print("❌ Node did not inject 'historical_context' or failed.")

if __name__ == "__main__":
    asyncio.run(main())
