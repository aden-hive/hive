import asyncio
import os
import random
import sys
import shutil
from pathlib import Path
import time

# Bootstrap path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "core"))

from framework.memory.hub import MemoryHub
from framework.memory.providers.local import LocalJSONLProvider
from framework.memory.provider import BaseEmbeddingProvider

class MockEmbedder(BaseEmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        # Simulate slight latency
        await asyncio.sleep(0.001)
        return [0.1] * 128

async def worker(hub: MemoryHub, worker_id: int):
    """Simulate a worker writing memories."""
    # Write normal
    await hub.remember(f"Worker {worker_id} reporting success", {"worker": worker_id}, outcome="success")
    
    # Write with PII
    await hub.remember(f"Worker {worker_id} using key sk-12345-{worker_id}", {"secret": f"pass_{worker_id}"}, outcome="failure")

async def main():
    print("🔥 Starting Memory Stress Test...")
    
    # Setup
    test_file = "stress_memory.jsonl"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    provider = LocalJSONLProvider(test_file)
    embedder = MockEmbedder()
    hub = MemoryHub(provider, embedder)
    
    start_time = time.time()
    
    # Run 50 concurrent workers
    tasks = [worker(hub, i) for i in range(50)]
    await asyncio.gather(*tasks)
    
    duration = time.time() - start_time
    print(f"✅ Completed 100 writes in {duration:.4f}s")
    
    # Validation
    print("\n🔍 Validating Data Integrity...")
    line_count = 0
    pii_leak = False
    
    with open(test_file, 'r') as f:
        for line in f:
            line_count += 1
            content = line.strip()
            if "sk-12345" in content and "********" not in content:
                pii_leak = True
                print(f"❌ PII LEAK: {content}")
            
    print(f"Total Records: {line_count} (Expected 100)")
    
    if line_count == 100:
        print("✅ Concurrency Check: PASS (No lost writes)")
    else:
        print(f"❌ Concurrency Check: FAIL (Lost {100 - line_count} writes)")
        
    if not pii_leak:
        print("✅ Privacy Check: PASS (No API keys found)")
    else:
        print("❌ Privacy Check: FAIL")
        
    # Test Cache Hit (Implicit)
    # If we call remember with same text, it should be faster if we measured detailed stats
    # For now we assume logic holds.

if __name__ == "__main__":
    asyncio.run(main())
