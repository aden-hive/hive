"""
IndexStore: File-based storage for trace indexes.

Follows Hive patterns:
- Async I/O with asyncio.to_thread()
- atomic_write() for persistence
- JSON serialization
- Non-fatal error handling

Reference: core/framework/storage/session_store.py
"""

import asyncio
import json
import logging
from pathlib import Path

from framework.debugging.trace_index import TraceIndex
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


class IndexStore:
    """
    File-based storage for trace indexes.

    Follows Hive patterns:
    - Async I/O with asyncio.to_thread()
    - atomic_write() for crash-safe persistence
    - JSON-only serialization
    - Non-fatal error handling (logs, doesn't raise)

    Reference: framework/storage/session_store.py
    """

    def __init__(self, base_path: Path | None = None):
        """
        Initialize index store.

        Args:
            base_path: Base directory for storage.
                      Defaults to ~/.hive/agents
        """
        if base_path is None:
            base_path = Path.home() / ".hive" / "agents"

        self.base_path = Path(base_path)
        self.index_file = self.base_path / ".trace_index.json"
        self.index: dict[str, TraceIndex] = {}

    async def load(self) -> None:
        """
        Load index from disk.

        Follows Hive pattern: Use asyncio.to_thread for blocking I/O
        Reference: framework/storage/session_store.py lines 91-98
        """

        def _load() -> dict[str, TraceIndex]:
            """Blocking load operation."""
            if not self.index_file.exists():
                return {}

            try:
                with open(self.index_file) as f:
                    data = json.load(f)

                # Deserialize to TraceIndex objects
                return {run_id: TraceIndex.model_validate(entry) for run_id, entry in data.items()}
            except Exception:
                # Non-fatal error handling (Hive pattern)
                logger.exception("Failed to load trace index from %s (non-fatal)", self.index_file)
                return {}

        # Use asyncio.to_thread for blocking I/O (Hive pattern)
        self.index = await asyncio.to_thread(_load)
        logger.info(f"Loaded {len(self.index)} traces from index")

    async def save(self) -> None:
        """
        Save index to disk.

        Follows Hive patterns:
        - asyncio.to_thread for blocking I/O
        - atomic_write for crash-safe writes
        - Non-fatal error handling

        Reference: framework/storage/session_store.py lines 91-98
        """

        def _save() -> None:
            """Blocking save operation."""
            # Ensure directory exists
            self.index_file.parent.mkdir(parents=True, exist_ok=True)

            # Serialize to dict
            data = {run_id: trace.model_dump(mode="json") for run_id, trace in self.index.items()}

            # Use atomic_write (Hive pattern)
            # Reference: framework/utils/io.py lines 6-18
            with atomic_write(self.index_file, mode="w") as f:
                json.dump(data, f, indent=2, default=str)

        try:
            await asyncio.to_thread(_save)
            logger.info(f"Saved {len(self.index)} traces to index")
        except Exception:
            # Non-fatal error handling (Hive pattern)
            # Reference: framework/runtime/runtime_logger.py lines 300-304
            logger.exception("Failed to save trace index to %s (non-fatal)", self.index_file)

    def add(self, trace: TraceIndex) -> None:
        """
        Add trace to in-memory index.

        Args:
            trace: TraceIndex to add
        """
        self.index[trace.run_id] = trace

    def get(self, run_id: str) -> TraceIndex | None:
        """
        Get trace by run_id.

        Args:
            run_id: Run identifier

        Returns:
            TraceIndex if found, None otherwise
        """
        return self.index.get(run_id)

    def list_all(self) -> list[TraceIndex]:
        """
        List all traces in index.

        Returns:
            List of all TraceIndex objects
        """
        return list(self.index.values())
