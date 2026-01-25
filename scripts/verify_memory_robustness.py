
import asyncio
import os
import shutil
import time
from typing import List
from framework.memory.hub import MemoryHub
from framework.memory.providers.local import LocalJSONLProvider
from framework.memory.provider import BaseEmbeddingProvider

class MockEmbedder(BaseEmbeddingProvider):
    async def embed(self, text: str) -> List[float]:
        # Return non-normalized vector [1, 1, 1] magnitude sqrt(3) ~ 1.732
        return [1.0, 1.0, 1.0]

async def main():
    test_file = "test_memory_robust.jsonl"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    embedder = MockEmbedder()
    provider = LocalJSONLProvider(file_path=test_file)
    hub = MemoryHub(provider, embedder)
    
    print("--- Test 1: Persistence & Normalization ---")
    # Store memory - should be normalized on save
    await hub.remember("Important rule", {}, outcome="success", source_type="system", agent_version="1.0.0")
    
    # Check if file exists
    assert os.path.exists(test_file)
    print("File created successfully.")
    
    # Recall
    results = await hub.recall("rule")
    assert len(results) > 0
    
    # Access internal index to verify vector
    # Force load if not loaded (recall does it)
    stored_rec = provider._index[0]
    print(f"Stored Vector: {stored_rec.vector}")
    
    # Check normalization: [1,1,1] -> [0.577, 0.577, 0.577]
    mag = sum(x*x for x in stored_rec.vector)
    print(f"Vector Magnitude (should be ~1.0): {mag}")
    assert abs(mag - 1.0) < 0.001
    
    # Check attributes
    print(f"Source Type: {stored_rec.source_type}")
    assert stored_rec.source_type == "system"
    assert stored_rec.agent_version == "1.0.0"
    
    print("--- Test 2: In-Memory Index Persistence ---")
    # Simulate restart
    provider_new = LocalJSONLProvider(file_path=test_file)
    # _load_index is triggered on first query/upsert
    await provider_new.query([1.0, 0.0, 0.0]) # trigger load
    
    assert len(provider_new._index) == 1
    loaded_rec = provider_new._index[0]
    assert loaded_rec.content == "Important rule"
    assert loaded_rec.source_type == "system"
    print("Persistence verified.")
    
    print("\nPASS: Memory Robustness Verified!")

    # Cleanup
    if os.path.exists(test_file):
        os.remove(test_file)

if __name__ == "__main__":
    asyncio.run(main())
