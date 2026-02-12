"""
TraceVectorStore: FAISS-based vector storage for trace embeddings.

Follows Hive patterns:
- Async I/O with asyncio.to_thread()
- File-based storage
- Type safety with Pydantic models
- Non-fatal error handling

Reference: LangChain FAISS documentation
"""

import asyncio
import json
import logging
from pathlib import Path

import faiss
import numpy as np

from framework.debugging.trace_index import TraceIndex

logger = logging.getLogger(__name__)


class TraceVectorStore:
    """
    FAISS-based vector storage for trace embeddings.

    Stores trace embeddings and provides efficient similarity search.
    Persists index and metadata to disk for durability.

    Follows Hive patterns:
    - Async I/O with asyncio.to_thread()
    - File-based storage (no external databases)
    - Non-fatal error handling
    """

    def __init__(
        self,
        storage_path: Path | None = None,
        dimension: int = 384,  # Default HuggingFace all-MiniLM-L6-v2 dimension
    ):
        """
        Initialize vector store.

        Args:
            storage_path: Path to store index and metadata.
                         Defaults to ~/.hive/agents/.vector_index/
            dimension: Embedding vector dimension
        """
        if storage_path is None:
            storage_path = Path.home() / ".hive" / "agents" / ".vector_index"

        self.storage_path = Path(storage_path)
        self.dimension = dimension

        # FAISS index for similarity search
        self.index: faiss.IndexFlatL2 | None = None

        # Metadata storage (run_id -> TraceIndex)
        self.metadata: dict[str, TraceIndex] = {}

        # Mapping from FAISS index position to run_id
        self.index_to_run_id: list[str] = []

    async def initialize(self) -> None:
        """
        Initialize or load existing index.

        Creates a new FAISS index or loads from disk if available.
        """
        # Try to load existing index
        if await self._index_exists():
            await self.load()
        else:
            # Create new index
            self.index = faiss.IndexFlatL2(self.dimension)
            logger.info("Created new FAISS index with dimension %d", self.dimension)

    async def add_traces(self, traces: list[TraceIndex], embeddings: list[list[float]]) -> None:
        """
        Add traces and their embeddings to the index.

        Args:
            traces: List of TraceIndex objects
            embeddings: Corresponding embedding vectors

        Raises:
            ValueError: If traces and embeddings lengths don't match
        """
        if len(traces) != len(embeddings):
            raise ValueError(
                f"Traces ({len(traces)}) and embeddings ({len(embeddings)}) must have same length"
            )

        if self.index is None:
            await self.initialize()

        def _add() -> None:
            """Blocking add operation."""
            # Convert embeddings to numpy array
            vectors = np.array(embeddings, dtype=np.float32)

            # Add to FAISS index
            self.index.add(vectors)

            # Store metadata
            for trace in traces:
                self.metadata[trace.run_id] = trace
                self.index_to_run_id.append(trace.run_id)

        await asyncio.to_thread(_add)
        logger.info("Added %d traces to vector index", len(traces))

    async def search(
        self, query_embedding: list[float], k: int = 5
    ) -> list[tuple[TraceIndex, float]]:
        """
        Search for similar traces.

        Args:
            query_embedding: Query embedding vector
            k: Number of results to return

        Returns:
            List of (TraceIndex, distance) tuples, sorted by similarity
        """
        if self.index is None or self.index.ntotal == 0:
            logger.warning("Vector index is empty")
            return []

        def _search() -> list[tuple[TraceIndex, float]]:
            """Blocking search operation."""
            # Convert query to numpy array
            query_vector = np.array([query_embedding], dtype=np.float32)

            # Search FAISS index
            distances, indices = self.index.search(query_vector, k)

            # Convert results to TraceIndex objects
            results = []
            for distance, idx in zip(distances[0], indices[0], strict=False):
                if idx >= 0 and idx < len(self.index_to_run_id):
                    run_id = self.index_to_run_id[idx]
                    if run_id in self.metadata:
                        trace = self.metadata[run_id]
                        results.append((trace, float(distance)))

            return results

        return await asyncio.to_thread(_search)

    async def save(self) -> None:
        """
        Save index and metadata to disk.

        Follows Hive patterns:
        - asyncio.to_thread for blocking I/O
        - Non-fatal error handling
        """
        if self.index is None:
            logger.debug("No index to save")
            return

        def _save() -> None:
            """Blocking save operation."""
            # Ensure directory exists
            self.storage_path.mkdir(parents=True, exist_ok=True)

            # Save FAISS index
            index_path = self.storage_path / "faiss.index"
            faiss.write_index(self.index, str(index_path))

            # Save metadata
            metadata_path = self.storage_path / "metadata.json"
            metadata_dict = {
                run_id: trace.model_dump(mode="json") for run_id, trace in self.metadata.items()
            }

            with open(metadata_path, "w") as f:
                json.dump(metadata_dict, f, indent=2, default=str)

            # Save index mapping
            mapping_path = self.storage_path / "index_mapping.json"
            with open(mapping_path, "w") as f:
                json.dump(self.index_to_run_id, f)

        try:
            await asyncio.to_thread(_save)
            logger.info("Saved vector index to %s", self.storage_path)
        except Exception:
            logger.exception("Failed to save vector index to %s (non-fatal)", self.storage_path)

    async def load(self) -> None:
        """
        Load index and metadata from disk.

        Follows Hive patterns:
        - asyncio.to_thread for blocking I/O
        - Non-fatal error handling
        """

        def _load() -> tuple[faiss.IndexFlatL2, dict, list]:
            """Blocking load operation."""
            # Load FAISS index
            index_path = self.storage_path / "faiss.index"
            if not index_path.exists():
                raise FileNotFoundError(f"Index not found at {index_path}")

            index = faiss.read_index(str(index_path))

            # Load metadata
            metadata_path = self.storage_path / "metadata.json"
            with open(metadata_path) as f:
                metadata_dict = json.load(f)

            metadata = {
                run_id: TraceIndex.model_validate(data) for run_id, data in metadata_dict.items()
            }

            # Load index mapping
            mapping_path = self.storage_path / "index_mapping.json"
            with open(mapping_path) as f:
                index_to_run_id = json.load(f)

            return index, metadata, index_to_run_id

        try:
            self.index, self.metadata, self.index_to_run_id = await asyncio.to_thread(_load)
            logger.info(
                "Loaded vector index with %d traces from %s", len(self.metadata), self.storage_path
            )
        except Exception:
            logger.exception("Failed to load vector index from %s (non-fatal)", self.storage_path)
            # Initialize new index on failure
            self.index = faiss.IndexFlatL2(self.dimension)

    async def _index_exists(self) -> bool:
        """
        Check if index files exist on disk.

        Returns:
            True if index exists, False otherwise
        """

        def _check() -> bool:
            """Blocking check operation."""
            index_path = self.storage_path / "faiss.index"
            metadata_path = self.storage_path / "metadata.json"
            mapping_path = self.storage_path / "index_mapping.json"

            return index_path.exists() and metadata_path.exists() and mapping_path.exists()

        return await asyncio.to_thread(_check)

    def size(self) -> int:
        """
        Get number of traces in the index.

        Returns:
            Number of indexed traces
        """
        if self.index is None:
            return 0
        return self.index.ntotal

    def clear(self) -> None:
        """
        Clear the index and metadata.

        Creates a fresh index.
        """
        self.index = faiss.IndexFlatL2(self.dimension)
        self.metadata = {}
        self.index_to_run_id = []
        logger.info("Cleared vector index")
