import json
import aiofiles
import math
import asyncio
import os
import time
from typing import List, Dict, Any
from ..provider import BaseVectorProvider, MemoryRecord

class LocalJSONLProvider(BaseVectorProvider):
    def __init__(self, file_path: str = "agent_memory.jsonl"):
        self.file_path = file_path
        self._lock = asyncio.Lock() # Ensure strict serial writes
        self._index: List[MemoryRecord] = []
        self._loaded = False

    async def _load_index(self):
        """Loads the entire JSONL into memory at startup (Lazy loading)."""
        if self._loaded:
            return
            
        self._index = []
        if not os.path.exists(self.file_path):
            self._loaded = True
            return

        async with aiofiles.open(self.file_path, mode='r') as f:
            async for line in f:
                if not line.strip(): continue
                try:
                    data = json.loads(line)
                    # Backwards compatibility: handle missing fields
                    record = MemoryRecord(
                        id=data.get("id"),
                        vector=data.get("vector"),
                        metadata=data.get("metadata", {}),
                        content=data.get("content"),
                        execution_outcome=data.get("execution_outcome"),
                        source_type=data.get("source_type", "user"),
                        agent_version=data.get("agent_version", "0.0.0"),
                        timestamp=data.get("timestamp", 0.0)
                    )
                    self._index.append(record)
                except (json.JSONDecodeError, Exception) as e:
                    # Robustness: Ignore corrupted lines to prevent crash, but log it
                    print(f"[{self.__class__.__name__}] Warning: Corrupted memory line ignored: {e}")
                    continue
        self._loaded = True

    # ROADMAP: Future implementation should switch to ChromaDB or Milvus 
    # for O(log N) ANN search performance using HNSW graphs. 
    # The current linear scan is a placeholder for zero-dependency local usage.
    def _normalize(self, v: List[float]) -> List[float]:
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            return v
        return [x / norm for x in v]

    async def upsert(self, record: MemoryRecord) -> bool:
        if not self._loaded:
            await self._load_index()

        # 1. Normalize Vector
        record.vector = self._normalize(record.vector)

        # 2. Update In-Memory Index
        # Check if exists (update) or new (append). For MVP assuming new IDs mostly.
        # Linear scan for update is slow, but upserts are rarer than reads.
        existing_idx = next((i for i, r in enumerate(self._index) if r.id == record.id), -1)
        if existing_idx >= 0:
            self._index[existing_idx] = record
        else:
            self._index.append(record)

        # 3. Persist to Disk (Robust Append)
        data = {
            "id": record.id,
            "vector": record.vector,
            "metadata": record.metadata,
            "content": record.content,
            "execution_outcome": record.execution_outcome,
            "source_type": record.source_type,
            "agent_version": record.agent_version,
            "timestamp": record.timestamp
        }
        
        async with self._lock: # Critical section
            async with aiofiles.open(self.file_path, mode='a') as f:
                await f.write(json.dumps(data) + "\n")
                await f.flush() # Ensure data is flushed to OS buffer
                os.fsync(f.fileno()) # Force write to disk
        return True

    async def query(self, vector: List[float], top_k: int = 3, filters: Dict[str, Any] = None) -> List[MemoryRecord]:
        if not self._loaded:
            await self._load_index()

        # Normalize query vector for Cosine Similarity
        query_vector = self._normalize(vector)

        # In-Memory Linear Scan (Fast for <100k records)
        results = []
        for item in self._index:
            # Apply filters
            if filters:
                match = True
                for key, value in filters.items():
                    # Check fields on the object first (e.g., source_type, execution_outcome)
                    if hasattr(item, key):
                        if getattr(item, key) != value:
                            match = False
                            break
                    # Also check dict access for raw json items if not object yet? 
                    # Wait, item IS MemoryRecord object here? NO, it's a dict from _load_index?
                    # In _load_index we store MemoryRecord objects in self._index.
                    # So 'item' in 'for item in self._index' is a MemoryRecord OBJECT.
                    
                    # Logic:
                    val = getattr(item, key, None)
                    if val is not None:
                         if val != value:
                            match = False
                            break
                    # Fallback to metadata
                    elif item.metadata.get(key) != value:
                        match = False
                        break
                if not match:
                    continue

            # Cosine Similarity: Dot product of normalized vectors
            sim = sum(a * b for a, b in zip(query_vector, item.vector))
            results.append((sim, item))

        # Sort by similarity desc
        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results[:top_k]]

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        # Deprecated: using inline doc product on normalized vectors
        return sum(a * b for a, b in zip(v1, v2))
