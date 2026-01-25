from typing import List, Dict, Any
from .provider import BaseVectorProvider, BaseEmbeddingProvider, MemoryRecord
from framework.utils.privacy import mask_sensitive_data

class MemoryHub:
    def __init__(self, provider: BaseVectorProvider, embedder: BaseEmbeddingProvider, cache_size: int = 1000):
        self.provider = provider
        self.embedder = embedder
        self._embedding_cache: Dict[str, List[float]] = {}
        self._cache_size = cache_size

    async def remember(self, text: str, metadata: Dict[str, Any], outcome: str | None = None, source_type: str = "user", agent_version: str = "0.0.0"):
        """The 'Learn' process: Mask -> Embed -> Save."""
        # 1. Privacy First
        clean_text = mask_sensitive_data(text)
        
        # 2. Embedding Cache Check
        if clean_text in self._embedding_cache:
            vector = self._embedding_cache[clean_text]
        else:
            vector = await self.embedder.embed(clean_text)
            # Simple cache management
            if len(self._embedding_cache) >= self._cache_size:
                self._embedding_cache.pop(next(iter(self._embedding_cache)))
            self._embedding_cache[clean_text] = vector
        
        # 3. Create Record and Persist
        import time
        record = MemoryRecord(
            id=metadata.get("run_id", f"gen_{time.time()}"),
            vector=vector,
            metadata=metadata,
            content=clean_text,
            execution_outcome=outcome,
            source_type=source_type,
            agent_version=agent_version,
            timestamp=time.time()
        )
        return await self.provider.upsert(record)

    async def recall(self, query: str, top_k: int = 3, filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """The 'Recall' process: Search similar memories."""
        query_vector = await self.embedder.embed(query)
        results = await self.provider.query(query_vector, top_k=top_k, filters=filters)
        
        # Return relevant content and metadata
        # Return relevant content, metadata, and outcome
        return [{
            "content": r.content, 
            "meta": r.metadata, 
            "outcome": r.execution_outcome
        } for r in results]
