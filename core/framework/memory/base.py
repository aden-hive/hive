"""
Base Memory Provider Interface.

Defines the abstract interface for memory providers in the Hive framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class MemoryEntry:
    """
    A single memory entry with content and metadata.

    Attributes:
        id: Unique identifier for this memory entry
        content: The text content to be stored and searched
        metadata: Additional metadata (e.g., source, node_id, timestamp)
        embedding: Vector embedding of the content (set after embedding)
        created_at: Timestamp when the entry was created
        relevance_score: Similarity score when retrieved (set during search)
    """

    id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    embedding: list[float] | None = None
    created_at: datetime = field(default_factory=datetime.now)
    relevance_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "embedding": self.embedding,
            "created_at": self.created_at.isoformat(),
            "relevance_score": self.relevance_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            content=data["content"],
            metadata=data.get("metadata", {}),
            embedding=data.get("embedding"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
            relevance_score=data.get("relevance_score", 0.0),
        )


class MemoryProvider(ABC):
    """
    Abstract base class for memory providers.

    Memory providers handle the storage and retrieval of agent memory,
    enabling context-aware decision making based on past experiences.

    Implementations can use different backends:
    - In-memory storage (for testing)
    - Vector databases (pgvector, Pinecone, etc.)
    - Hybrid approaches
    """

    @abstractmethod
    async def store(self, entry: MemoryEntry) -> str:
        """
        Store a memory entry.

        Args:
            entry: The memory entry to store

        Returns:
            The ID of the stored entry
        """
        pass

    @abstractmethod
    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """
        Retrieve relevant memory entries based on a query.

        Args:
            query: The search query
            top_k: Maximum number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of relevant memory entries, ranked by relevance
        """
        pass

    @abstractmethod
    async def retrieve_by_embedding(
        self,
        embedding: list[float],
        top_k: int = 5,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """
        Retrieve relevant memory entries based on an embedding vector.

        Args:
            embedding: The query embedding vector
            top_k: Maximum number of results to return
            filter_metadata: Optional metadata filters

        Returns:
            List of relevant memory entries, ranked by similarity
        """
        pass

    @abstractmethod
    async def delete(self, entry_id: str) -> bool:
        """
        Delete a memory entry.

        Args:
            entry_id: The ID of the entry to delete

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def clear(self) -> None:
        """Clear all memory entries."""
        pass

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of stored entries."""
        pass
