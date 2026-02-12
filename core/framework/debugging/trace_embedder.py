"""
TraceEmbedder: Generates embeddings for trace documents.

Follows Hive patterns:
- Async I/O with asyncio.to_thread()
- Type safety with Pydantic models
- LangChain integration
- Non-fatal error handling

Reference: LangChain documentation for embeddings
"""

import asyncio
import logging
from typing import Protocol

try:
    from langchain_community.embeddings import HuggingFaceEmbeddings

    DEFAULT_EMBEDDINGS_AVAILABLE = True
except ImportError:
    DEFAULT_EMBEDDINGS_AVAILABLE = False

from framework.debugging.trace_index import TraceIndex

logger = logging.getLogger(__name__)


class EmbeddingsProvider(Protocol):
    """Protocol for embeddings providers."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple documents."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        ...


class TraceEmbedder:
    """
    Generates embeddings for trace documents using LangChain.

    Converts TraceIndex objects into text documents and generates
    embeddings using Claude's embeddings model via LangChain.

    Follows Hive patterns:
    - Async I/O with asyncio.to_thread()
    - Type safety with Pydantic
    - Non-fatal error handling
    """

    def __init__(
        self,
        embeddings_provider: EmbeddingsProvider | None = None,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
    ):
        """
        Initialize trace embedder.

        Args:
            embeddings_provider: Custom embeddings provider. If None,
                                uses HuggingFaceEmbeddings (local, no API key needed).
            model_name: HuggingFace model name for default embeddings.
                       Default is a small, fast model suitable for local use.
        """
        if embeddings_provider is None:
            if not DEFAULT_EMBEDDINGS_AVAILABLE:
                raise ImportError(
                    "langchain_community is required for default embeddings. "
                    "Install with: pip install langchain-community"
                )
            # Use HuggingFace embeddings (local, no API needed)
            self.embeddings = HuggingFaceEmbeddings(model_name=model_name)
        else:
            self.embeddings = embeddings_provider

    def trace_to_document(self, trace: TraceIndex) -> str:
        """
        Convert TraceIndex to searchable text document.

        Creates a structured text representation that captures:
        - Run metadata (status, quality, timing)
        - Error information (if any)
        - Node execution sequence
        - Performance metrics

        Args:
            trace: TraceIndex to convert

        Returns:
            Text document suitable for embedding
        """
        parts = [
            f"Run ID: {trace.run_id}",
            f"Agent: {trace.agent_id}",
            f"Status: {trace.status}",
            f"Execution Quality: {trace.execution_quality}",
            f"Total Latency: {trace.total_latency_ms}ms",
            f"Total Tokens: {trace.total_tokens}",
            f"Node Count: {trace.node_count}",
        ]

        # Add node sequence
        if trace.node_ids:
            parts.append(f"Nodes Executed: {' -> '.join(trace.node_ids)}")

        # Add error information if present
        if trace.error_message:
            parts.append(f"Error: {trace.error_message}")
            if trace.failed_node_id:
                parts.append(f"Failed at Node: {trace.failed_node_id}")

        return "\n".join(parts)

    async def embed_trace(self, trace: TraceIndex) -> list[float]:
        """
        Generate embedding for a single trace.

        Follows Hive pattern: asyncio.to_thread for blocking I/O.

        Args:
            trace: TraceIndex to embed

        Returns:
            Embedding vector

        Raises:
            Exception: If embedding generation fails
        """
        document = self.trace_to_document(trace)

        def _embed() -> list[float]:
            """Blocking embed operation."""
            return self.embeddings.embed_query(document)

        return await asyncio.to_thread(_embed)

    async def embed_traces(self, traces: list[TraceIndex]) -> list[list[float]]:
        """
        Generate embeddings for multiple traces (batch).

        More efficient than calling embed_trace repeatedly.

        Follows Hive pattern: asyncio.to_thread for blocking I/O.

        Args:
            traces: List of TraceIndex objects

        Returns:
            List of embedding vectors
        """
        documents = [self.trace_to_document(trace) for trace in traces]

        def _embed_batch() -> list[list[float]]:
            """Blocking batch embed operation."""
            return self.embeddings.embed_documents(documents)

        return await asyncio.to_thread(_embed_batch)

    async def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.

        Args:
            query: Search query text

        Returns:
            Embedding vector
        """

        def _embed() -> list[float]:
            """Blocking embed operation."""
            return self.embeddings.embed_query(query)

        return await asyncio.to_thread(_embed)
