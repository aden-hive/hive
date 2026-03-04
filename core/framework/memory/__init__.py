"""
Semantic Memory Layer for Hive Framework.

This module provides vector-ranked semantic memory capabilities to resolve
context blindspots during long-running agent executions.

Key Components:
- MemoryProvider: Base interface for memory providers
- VectorMemoryProvider: Embedding-based semantic memory with similarity search
- EmbeddingProvider: Interface for embedding generation
- VectorStore: Interface for vector storage and retrieval
"""

from framework.memory.base import MemoryEntry, MemoryProvider
from framework.memory.embedding import (
    EmbeddingProvider,
    MockEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from framework.memory.vector_memory import VectorMemoryProvider
from framework.memory.vector_store import InMemoryVectorStore, VectorStore

__all__ = [
    "MemoryProvider",
    "MemoryEntry",
    "VectorMemoryProvider",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "MockEmbeddingProvider",
    "VectorStore",
    "InMemoryVectorStore",
]
