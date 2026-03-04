"""
Vector-Ranked Semantic Memory Provider.

Provides semantic memory capabilities using vector embeddings for context
retrieval and similarity-based search.
"""

from dataclasses import dataclass, field
from typing import Any

from framework.memory.base import MemoryEntry, MemoryProvider
from framework.memory.embedding import EmbeddingProvider
from framework.memory.vector_store import VectorStore


@dataclass
class SemanticMemoryConfig:
    """
    Configuration for semantic memory.

    Attributes:
        embedding_provider: Provider for generating text embeddings
        vector_store: Storage backend for embeddings
        top_k: Number of results to return during retrieval
        metadata_filter: Default metadata filters (e.g., source="node_x")
    """

    embedding_provider: EmbeddingProvider
    vector_store: VectorStore
    top_k: int = 5
    metadata_filter: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.metadata_filter is None:
            self.metadata_filter = {}


class VectorMemoryProvider(MemoryProvider):
    """
    Semantic memory provider that uses vector embeddings for context retrieval.

    This provider enables:
    - Semantic similarity search instead of chronological search
    - Context-aware decision making based on past experiences
    - Token-efficient retrieval of relevant historical context
    - Metadata filtering for focused search

    Example:
        # Create provider with OpenAI embeddings
        embedding_provider = OpenAIEmbeddingProvider()
        vector_store = InMemoryVectorStore()
        memory = VectorMemoryProvider(embedding_provider, vector_store)

        # Store a memory
        entry = MemoryEntry(
            id="entry_1",
            content="User prefers Python over JavaScript for data processing",
            metadata={"source": "user_pref", "category": "tech"},
        )
        await memory.store(entry)

        # Retrieve relevant memories
        results = await memory.retrieve(
            "What framework does the user prefer?",
            top_k=3,
            filter_metadata={"category": "tech"},
        )
    """

    top_k: int = 5

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        metadata_filter: dict[str, Any] | None = None,
        top_k: int = 5,
    ):
        """
        Initialize the vector memory provider.

        Args:
            embedding_provider: Provider for generating text embeddings
            vector_store: Storage backend for vector embeddings
            metadata_filter: Default metadata filters
            top_k: Number of results to return
        """
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.top_k = top_k
        self.metadata_filter = metadata_filter or {}
        """
        Initialize the vector memory provider.

        Args:
            embedding_provider: Provider for generating text embeddings
            vector_store: Storage backend for vector embeddings
        """
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store

    async def store(self, entry: MemoryEntry) -> str:
        """
        Store a memory entry and generate its embedding.

        Args:
            entry: The memory entry to store (metadata will be merged with defaults)

        Returns:
            The ID of the stored entry
        """
        # Merge metadata with defaults
        entry.metadata = {**self.metadata_filter, **entry.metadata}

        # Generate embedding if not already set
        if entry.embedding is None:
            entry.embedding = await self.embedding_provider.embed(entry.content)

        # Store the entry
        entry_id = await self.vector_store.upsert(entry)
        entry.id = entry_id
        return entry_id

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """
        Retrieve relevant memory entries based on semantic similarity.

        Args:
            query: The search query
            top_k: Maximum number of results to return (uses default if None)
            filter_metadata: Optional metadata filters (merges with defaults)

        Returns:
            List of relevant memory entries, ranked by relevance score
        """
        if top_k is None:
            top_k = self.top_k

        # Merge filter metadata with defaults
        filters = {**self.metadata_filter, **(filter_metadata or {})}

        # Generate embedding for query
        query_embedding = await self.embedding_provider.embed(query)

        # Search for similar entries
        results = await self.vector_store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_metadata=filters if filters else None,
        )

        return results

    async def retrieve_by_embedding(
        self,
        embedding: list[float],
        top_k: int | None = None,
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
        if top_k is None:
            top_k = self.top_k

        filters = {**self.metadata_filter, **(filter_metadata or {})}

        results = await self.vector_store.search(
            query_embedding=embedding,
            top_k=top_k,
            filter_metadata=filters if filters else None,
        )

        return results

    async def delete(self, entry_id: str) -> bool:
        """
        Delete a memory entry.

        Args:
            entry_id: The ID of the entry to delete

        Returns:
            True if deleted, False if not found
        """
        return await self.vector_store.delete(entry_id)

    async def clear(self) -> None:
        """Clear all memory entries."""
        await self.vector_store.clear()

    async def count(self) -> int:
        """Return the total number of stored entries."""
        return await self.vector_store.count()
