
import asyncio
import os
import shutil
from typing import List
from framework.memory.hub import MemoryHub
from framework.memory.providers.local import LocalJSONLProvider
from framework.memory.provider import BaseEmbeddingProvider

class MockEmbedder(BaseEmbeddingProvider):
    async def embed(self, text: str) -> List[float]:
        # Simple deterministic embedding for testing
        return [0.1] * 3

async def main():
    test_file = "test_memory_filtering.jsonl"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    embedder = MockEmbedder()
    provider = LocalJSONLProvider(file_path=test_file)
    hub = MemoryHub(provider, embedder)
    
    # store memories
    print("Storing memories...")
    await hub.remember("I deployed successfully", {"run_id": "1"}, outcome="success")
    await hub.remember("I failed to deploy", {"run_id": "2"}, outcome="failure")
    await hub.remember("Another success deployment", {"run_id": "3"}, outcome="success")
    
    # Test 1: Recall Success
    print("\n--- Test 1: Recall Success ---")
    success_memories = await hub.recall("deploy", filters={"execution_outcome": "success"})
    print(f"Found {len(success_memories)} success memories")
    for mem in success_memories:
        print(f" - {mem['content']}")
        
    assert len(success_memories) == 2
    
    # Test 2: Recall Failure
    print("\n--- Test 2: Recall Failure ---")
    failure_memories = await hub.recall("deploy", filters={"execution_outcome": "failure"})
    print(f"Found {len(failure_memories)} failure memories")
    for mem in failure_memories:
        print(f" - {mem['content']}")
        
    assert len(failure_memories) == 1
    
    # Test 3: Recall All (no filter)
    print("\n--- Test 3: Recall All ---")
    all_memories = await hub.recall("deploy")
    print(f"Found {len(all_memories)} total memories")
    
    assert len(all_memories) == 3

    print("\nPASS: All filtering tests passed!")
    
    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(main())
