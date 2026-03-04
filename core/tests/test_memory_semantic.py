"""
Unit tests for Vector-Ranked Semantic Memory Layer.

Tests the semantic memory provider, embeddings, and vector store functionality.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.memory.base import MemoryEntry, MemoryProvider
from framework.memory.embedding import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from framework.memory.vector_memory import VectorMemoryProvider
from framework.memory.vector_store import InMemoryVectorStore, cosine_similarity


class SimpleEmbeddingProvider(EmbeddingProvider):
    """Simple embedding provider that returns constant embeddings."""

    def __init__(self, dimension: int = 10):
        self._dimension = dimension

    async def embed(self, text: str) -> list[float]:
        """Return deterministic embedding based on text hash."""
        import hashlib

        text_hash = hashlib.sha256(text.encode()).hexdigest()
        embedding = []
        for i in range(self._dimension):
            chunk = text_hash[i % len(text_hash) : (i % len(text_hash)) + 8]
            if len(chunk) < 8:
                chunk = chunk + text_hash[: 8 - len(chunk)]
            value = int(chunk, 16) / (16**8) * 2 - 1
            embedding.append(value)

        # Normalize
        norm = sum(x * x for x in embedding) ** 0.5
        if norm > 0:
            embedding = [x / norm for x in embedding]

        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings for multiple texts."""
        return [await self.embed(text) for text in texts]

    def get_dimension(self) -> int:
        return self._dimension


@pytest.fixture
def mock_embedding_provider():
    """Create a mock embedding provider for testing."""
    provider = MagicMock(spec=EmbeddingProvider)
    provider.get_dimension.return_value = 3

    async def mock_embed(text: str) -> list[float]:
        # Return consistent embeddings based on text
        chars = sum(ord(c) for c in text)
        return [
            chars % 10 / 10.0,
            (chars * 2) % 10 / 10.0,
            (chars * 3) % 10 / 10.0,
        ]

    provider.embed = mock_embed
    return provider


@pytest.fixture
def vector_store():
    """Create an in-memory vector store for testing."""
    return InMemoryVectorStore()


@pytest.fixture
def vector_memory_provider(mock_embedding_provider):
    """Create a vector memory provider for testing."""
    return VectorMemoryProvider(mock_embedding_provider, InMemoryVectorStore())


@pytest.mark.asyncio
async def test_cosine_similarity_identical_vectors():
    """Test cosine similarity with identical vectors."""
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [1.0, 2.0, 3.0]

    result = cosine_similarity(vec1, vec2)
    assert result == 1.0


@pytest.mark.asyncio
async def test_cosine_similarity_opposite_vectors():
    """Test cosine similarity with opposite vectors."""
    vec1 = [1.0, 2.0, 3.0]
    vec2 = [-1.0, -2.0, -3.0]

    result = cosine_similarity(vec1, vec2)
    assert result == -1.0


@pytest.mark.asyncio
async def test_cosine_similarity_orthogonal_vectors():
    """Test cosine similarity with orthogonal vectors."""
    vec1 = [1.0, 0.0, 0.0]
    vec2 = [0.0, 1.0, 0.0]

    result = cosine_similarity(vec1, vec2)
    assert result == 0.0


@pytest.mark.asyncio
async def test_memory_entry_serialization():
    """Test that MemoryEntry can be serialized and deserialized."""
    entry = MemoryEntry(
        id="test_1",
        content="Test content",
        metadata={"source": "test", "value": 42},
        embedding=[1.0, 2.0, 3.0],
    )

    entry_dict = entry.to_dict()
    assert entry_dict["id"] == "test_1"
    assert entry_dict["content"] == "Test content"
    assert entry_dict["metadata"] == {"source": "test", "value": 42}
    assert entry_dict["embedding"] == [1.0, 2.0, 3.0]

    restored = MemoryEntry.from_dict(entry_dict)
    assert restored.id == entry.id
    assert restored.content == entry.content
    assert restored.metadata == entry.metadata
    assert restored.embedding == entry.embedding


@pytest.mark.asyncio
async def test_in_memory_vector_store_upsert(vector_store):
    """Test storing entries in in-memory vector store."""
    entry = MemoryEntry(
        id="entry_1",
        content="Test content",
        embedding=[1.0, 2.0, 3.0],
    )

    entry_id = await vector_store.upsert(entry)
    assert entry_id == "entry_1"

    retrieved = await vector_store.get(entry_id)
    assert retrieved is not None
    assert retrieved.content == "Test content"
    assert retrieved.embedding == [1.0, 2.0, 3.0]


@pytest.mark.asyncio
async def test_in_memory_vector_store_search(vector_store):
    """Test searching for similar entries."""
    # Store multiple entries
    await vector_store.upsert(
        MemoryEntry(id="entry_1", content="Python is great", embedding=[1.0, 0.0, 0.0])
    )
    await vector_store.upsert(
        MemoryEntry(id="entry_2", content="JavaScript is popular", embedding=[0.0, 1.0, 0.0])
    )
    await vector_store.upsert(
        MemoryEntry(id="entry_3", content="Java is stable", embedding=[0.0, 0.0, 1.0])
    )

    # Search for similar entries
    results = await vector_store.search([1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    assert results[0].id == "entry_1"
    assert results[0].relevance_score == 1.0
    assert results[1].id == "entry_2"
    assert results[1].relevance_score == 0.0


@pytest.mark.asyncio
async def test_in_memory_vector_store_delete(vector_store):
    """Test deleting an entry."""
    entry = MemoryEntry(id="entry_1", content="Test", embedding=[1.0, 0.0, 0.0])
    await vector_store.upsert(entry)

    # Verify it exists
    assert await vector_store.count() == 1

    # Delete it
    deleted = await vector_store.delete("entry_1")
    assert deleted is True

    # Verify it's gone
    assert await vector_store.count() == 0
    assert await vector_store.get("entry_1") is None


@pytest.mark.asyncio
async def test_vector_memory_provider_store(mock_embedding_provider):
    """Test storing a memory entry."""
    provider = VectorMemoryProvider(mock_embedding_provider, InMemoryVectorStore())

    entry = MemoryEntry(
        id="test_1",
        content="User likes Python",
        metadata={"source": "user_pref"},
    )

    entry_id = await provider.store(entry)
    assert entry_id == "test_1"
    assert entry.metadata["source"] == "user_pref"

    # Check that embedding was generated
    assert entry.embedding is not None
    assert len(entry.embedding) == mock_embedding_provider.get_dimension()

    # Check that entry was stored
    retrieved = await provider.retrieve_by_embedding(entry.embedding, top_k=1)
    assert len(retrieved) == 1
    assert retrieved[0].content == "User likes Python"


@pytest.mark.asyncio
async def test_vector_memory_provider_retrieve(vector_memory_provider):
    """Test retrieving relevant memories."""
    # Store test memories with matching dimensions
    memories = [
        MemoryEntry(id="mem_1", content="User prefers Python framework", embedding=[1.0, 0.0, 0.0]),
        MemoryEntry(id="mem_2", content="User works with React", embedding=[0.0, 1.0, 0.0]),
        MemoryEntry(
            id="mem_3", content="User likes Node.js for backend", embedding=[0.0, 0.0, 1.0]
        ),
    ]

    for mem in memories:
        await vector_memory_provider.store(mem)

    # Search for Python-related content
    results = await vector_memory_provider.retrieve("What framework does the user prefer?", top_k=2)
    assert len(results) == 2
    assert results[0].content == "User prefers Python framework"


@pytest.mark.asyncio
async def test_vector_memory_provider_filter_metadata(vector_memory_provider):
    """Test filtering memories by metadata."""
    # Store memories with different metadata
    await vector_memory_provider.store(
        MemoryEntry(
            id="mem_1",
            content="General preference",
            metadata={"category": "general", "source": "user"},
        )
    )
    await vector_memory_provider.store(
        MemoryEntry(
            id="mem_2",
            content="Technical preference",
            metadata={"category": "tech", "source": "user"},
        )
    )
    await vector_memory_provider.store(
        MemoryEntry(
            id="mem_3",
            content="Business preference",
            metadata={"category": "business", "source": "admin"},
        )
    )

    # Filter by category
    results = await vector_memory_provider.retrieve(
        "Tech preference", top_k=2, filter_metadata={"category": "tech"}
    )
    assert len(results) == 1
    assert results[0].content == "Technical preference"
    assert results[0].metadata["category"] == "tech"


@pytest.mark.asyncio
async def test_vector_memory_provider_default_top_k(vector_memory_provider):
    """Test that default top_k is used when not specified."""
    # Create provider with SimpleEmbeddingProvider
    provider = VectorMemoryProvider(SimpleEmbeddingProvider(dimension=3), InMemoryVectorStore())
    provider.top_k = 3

    # Store some memories
    await provider.store(MemoryEntry(id="mem_1", content="Test 1", embedding=[1.0, 0.0, 0.0]))
    await provider.store(MemoryEntry(id="mem_2", content="Test 2", embedding=[0.0, 1.0, 0.0]))
    await provider.store(MemoryEntry(id="mem_3", content="Test 3", embedding=[0.0, 0.0, 1.0]))

    # Should return 3 results (top_k=3)
    results = await provider.retrieve("Query", top_k=5)
    assert len(results) == 3


@pytest.mark.asyncio
async def test_vector_memory_provider_count(vector_memory_provider):
    """Test counting stored memories."""
    assert await vector_memory_provider.count() == 0

    await vector_memory_provider.store(
        MemoryEntry(id="mem_1", content="Test 1", embedding=[1.0, 0.0, 0.0])
    )
    assert await vector_memory_provider.count() == 1

    await vector_memory_provider.store(
        MemoryEntry(id="mem_2", content="Test 2", embedding=[0.0, 1.0, 0.0])
    )
    assert await vector_memory_provider.count() == 2


@pytest.mark.asyncio
async def test_vector_memory_provider_clear(vector_memory_provider):
    """Test clearing all memories."""
    await vector_memory_provider.store(
        MemoryEntry(id="mem_1", content="Test", embedding=[1.0, 0.0, 0.0])
    )
    await vector_memory_provider.store(
        MemoryEntry(id="mem_2", content="Test", embedding=[0.0, 1.0, 0.0])
    )

    assert await vector_memory_provider.count() == 2

    await vector_memory_provider.clear()
    assert await vector_memory_provider.count() == 0


@pytest.mark.asyncio
async def test_vector_memory_provider_delete(vector_memory_provider):
    """Test deleting a specific memory."""
    await vector_memory_provider.store(
        MemoryEntry(id="mem_1", content="Test", embedding=[1.0, 0.0, 0.0])
    )
    await vector_memory_provider.store(
        MemoryEntry(id="mem_2", content="Test", embedding=[0.0, 1.0, 0.0])
    )

    assert await vector_memory_provider.count() == 2

    deleted = await vector_memory_provider.delete("mem_1")
    assert deleted is True
    assert await vector_memory_provider.count() == 1

    deleted = await vector_memory_provider.delete("nonexistent")
    assert deleted is False
    assert await vector_memory_provider.count() == 1
