"""
Vector Store Interface and Implementations.

Provides storage and similarity search for vector embeddings.
"""

import math
from abc import ABC, abstractmethod
from typing import Any

from framework.memory.base import MemoryEntry


class VectorStore(ABC):
    """
    Abstract base class for vector stores.

    Vector stores handle the persistence and retrieval of vector embeddings
    with support for similarity search.
    """

    @abstractmethod
    async def upsert(self, entry: MemoryEntry) -> str:
        """
        Insert or update a memory entry.

        Args:
            entry: The memory entry to store (must have embedding set)

        Returns:
            The ID of the stored entry
        """
        pass

    @abstractmethod
    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """
        Search for similar entries using cosine similarity.

        Args:
            query_embedding: The query vector
            top_k: Maximum number of results
            filter_metadata: Optional metadata filters

        Returns:
            List of matching entries with relevance_score set
        """
        pass

    @abstractmethod
    async def delete(self, entry_id: str) -> bool:
        """
        Delete an entry by ID.

        Args:
            entry_id: The ID of the entry to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all entries."""
        pass

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of stored entries."""
        pass

    @abstractmethod
    async def get(self, entry_id: str) -> MemoryEntry | None:
        """
        Get an entry by ID.

        Args:
            entry_id: The ID of the entry to retrieve

        Returns:
            The entry if found, None otherwise
        """
        pass


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """
    Calculate cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity score between -1 and 1
    """
    if len(vec1) != len(vec2):
        raise ValueError("Vectors must have the same dimension")

    dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))

    if norm1 == 0 or norm2 == 0:
        return 0.0

    return dot_product / (norm1 * norm2)


class InMemoryVectorStore(VectorStore):
    """
    In-memory vector store for testing and development.

    Stores entries in memory with brute-force similarity search.
    Not suitable for production use with large datasets.
    """

    def __init__(self):
        self._entries: dict[str, MemoryEntry] = {}

    async def upsert(self, entry: MemoryEntry) -> str:
        """Store an entry in memory."""
        if entry.embedding is None:
            raise ValueError("Entry must have an embedding")
        self._entries[entry.id] = entry
        return entry.id

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Search for similar entries using brute-force cosine similarity."""
        results: list[tuple[float, MemoryEntry]] = []

        for entry in self._entries.values():
            if entry.embedding is None:
                continue

            if filter_metadata:
                match = all(entry.metadata.get(k) == v for k, v in filter_metadata.items())
                if not match:
                    continue

            similarity = cosine_similarity(query_embedding, entry.embedding)
            results.append((similarity, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        top_results = results[:top_k]

        for similarity, entry in top_results:
            entry.relevance_score = similarity

        return [entry for _, entry in top_results]

    async def delete(self, entry_id: str) -> bool:
        """Delete an entry by ID."""
        if entry_id in self._entries:
            del self._entries[entry_id]
            return True
        return False

    async def clear(self) -> None:
        """Clear all entries."""
        self._entries.clear()

    async def count(self) -> int:
        """Return the total number of stored entries."""
        return len(self._entries)

    async def get(self, entry_id: str) -> MemoryEntry | None:
        """Get an entry by ID."""
        return self._entries.get(entry_id)
