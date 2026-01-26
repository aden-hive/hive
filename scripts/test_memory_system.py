import asyncio
import os
import shutil
import random
import sys
from pathlib import Path

# Bootstrap path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "core"))

from framework.memory.provider import BaseEmbeddingProvider
from framework.memory.providers.local import LocalJSONLProvider
from framework.memory.hub import MemoryHub

# 1. Mock Embedder (Deterministic for testing)
class MockEmbedder(BaseEmbeddingProvider):
    async def embed(self, text: str) -> list[float]:
        # Simple deterministic vector based on string length and chars
        # This ensures "hello" is always close to "hello" but far from "world" if we wanted
        # For simplicity, we just generate random but consistent vectors for specific keys if needed
        # Or just random
        
        # Better mock: Keyword vector
        # Vector size 3: [contains_hello, contains_secret, length/100]
        v = [0.0, 0.0, 0.0]
        if "hello" in text.lower(): v[0] = 1.0
        if "secret" in text.lower(): v[1] = 1.0
        v[2] = min(len(text) / 100.0, 1.0)
        return v

async def main():
    print("🧠 Testing Persistent Memory Hub...")
    
    # Setup
    test_file = "test_memory.jsonl"
    if os.path.exists(test_file):
        os.remove(test_file)
        
    provider = LocalJSONLProvider(test_file)
    embedder = MockEmbedder()
    hub = MemoryHub(provider, embedder)
    
    # 1. Test Remember (with PII)
    print("\n📝 Storing memories...")
    await hub.remember("Hello world, this is a normal memory.", {"type": "chat"})
    await hub.remember("My secret api_key is sk-12345, don't tell anyone!", {"type": "secret"})
    
    # 2. Verify File Content (Redaction check)
    print("\n🔍 Verifying masking on disk...")
    with open(test_file, 'r') as f:
        content = f.read()
        print(f"File content:\n{content}")
        if "sk-12345" not in content and "********" in content:
            print("✅ PII successfully redacted!")
        else:
            print("❌ PII LEAKED or not masked!")
            
    # 3. Test Recall
    print("\n💭 Recalling 'hello'...")
    results = await hub.recall("Hello there")
    
    print(f"Found {len(results)} matches.")
    if len(results) > 0:
        print(f"Top match: {results[0]['content']}")
        if "Hello world" in results[0]['content']:
            print("✅ Context retrieval working (Cosine Similarity)!")
        else:
             print("⚠️ Retrieve unexpected result (Mock embedding logic issue?)")
    else:
        print("❌ No matches found!")

if __name__ == "__main__":
    asyncio.run(main())
