from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class MemoryRecord:
    id: str
    vector: List[float]
    metadata: Dict[str, Any]
    content: str # The masked text content
    execution_outcome: Optional[str] = None # 'success', 'failure', etc.
    source_type: str = "user" # 'user', 'system', 'internal'
    agent_version: str = "0.0.0"
    timestamp: float = 0.0

class BaseVectorProvider(ABC):
    @abstractmethod
    async def upsert(self, record: MemoryRecord) -> bool:
        """Persist or update a memory record."""
        pass

    @abstractmethod
    async def query(self, vector: List[float], top_k: int = 3, filters: Dict[str, Any] = None) -> List[MemoryRecord]:
        """Search for semantically similar memories."""
        pass

class BaseEmbeddingProvider(ABC):
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Transform text into a numeric vector."""
        pass
