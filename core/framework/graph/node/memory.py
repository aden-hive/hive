"""Shared memory for node state management.

Provides thread-safe state sharing between nodes in a graph execution.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from framework.errors import MemoryWriteError

logger = logging.getLogger(__name__)


@dataclass
class SharedMemory:
    """Shared state between nodes in a graph execution.

    Nodes read and write to shared memory using typed keys.
    The memory is scoped to a single run.

    For parallel execution, use write_async() which provides per-key locking
    to prevent race conditions when multiple nodes write concurrently.
    """

    _data: dict[str, Any] = field(default_factory=dict)
    _allowed_read: set[str] = field(default_factory=set)
    _allowed_write: set[str] = field(default_factory=set)
    # Locks for thread-safe parallel execution
    _lock: asyncio.Lock | None = field(default=None, repr=False)
    _key_locks: dict[str, asyncio.Lock] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        """Initialize the main lock if not provided."""
        if self._lock is None:
            self._lock = asyncio.Lock()

    def read(self, key: str) -> Any:
        """Read a value from shared memory."""
        if self._allowed_read and key not in self._allowed_read:
            raise PermissionError(f"Node not allowed to read key: {key}")
        return self._data.get(key)

    def write(self, key: str, value: Any, validate: bool = True) -> None:
        """Write a value to shared memory.

        Args:
            key: The memory key to write to
            value: The value to write
            validate: If True, check for suspicious content (default True)

        Raises:
            PermissionError: If node doesn't have write permission
            MemoryWriteError: If value appears to be hallucinated content
        """
        if self._allowed_write and key not in self._allowed_write:
            raise PermissionError(f"Node not allowed to write key: {key}")

        if validate and isinstance(value, str):
            # Check for obviously hallucinated content
            if len(value) > 5000:
                # Long strings that look like code are suspicious
                if self._contains_code_indicators(value):
                    logger.warning(
                        f"⚠ Suspicious write to key '{key}': appears to be code "
                        f"({len(value)} chars). Consider using validate=False if intended."
                    )
                    raise MemoryWriteError(
                        f"Rejected suspicious content for key '{key}': "
                        f"appears to be hallucinated code ({len(value)} chars). "
                        "If this is intentional, use validate=False."
                    )

        self._data[key] = value

    async def write_async(self, key: str, value: Any, validate: bool = True) -> None:
        """Thread-safe async write with per-key locking.

        Use this method when multiple nodes may write concurrently during
        parallel execution. Each key has its own lock to minimize contention.

        Args:
            key: The memory key to write to
            value: The value to write
            validate: If True, check for suspicious content (default True)

        Raises:
            PermissionError: If node doesn't have write permission
            MemoryWriteError: If value appears to be hallucinated content
        """
        # Check permissions first (no lock needed)
        if self._allowed_write and key not in self._allowed_write:
            raise PermissionError(f"Node not allowed to write key: {key}")

        # Ensure key has a lock (double-checked locking pattern)
        if key not in self._key_locks:
            async with self._lock:
                if key not in self._key_locks:
                    self._key_locks[key] = asyncio.Lock()

        # Acquire per-key lock and write
        async with self._key_locks[key]:
            if validate and isinstance(value, str):
                if len(value) > 5000:
                    if self._contains_code_indicators(value):
                        logger.warning(
                            f"⚠ Suspicious write to key '{key}': appears to be code "
                            f"({len(value)} chars). Consider using validate=False if intended."
                        )
                        raise MemoryWriteError(
                            f"Rejected suspicious content for key '{key}': "
                            f"appears to be hallucinated code ({len(value)} chars). "
                            "If this is intentional, use validate=False."
                        )
            self._data[key] = value

    def _contains_code_indicators(self, value: str) -> bool:
        """Check for code patterns in a string using sampling for efficiency.

        For strings under 10KB, checks the entire content.
        For longer strings, samples at strategic positions to balance
        performance with detection accuracy.

        Args:
            value: The string to check for code indicators

        Returns:
            True if code indicators are found, False otherwise
        """
        code_indicators = [
            # Python
            "```python",
            "def ",
            "class ",
            "import ",
            "async def ",
            "from ",
            # JavaScript/TypeScript
            "function ",
            "const ",
            "let ",
            "=> {",
            "require(",
            "export ",
            # SQL
            "SELECT ",
            "INSERT ",
            "UPDATE ",
            "DELETE ",
            "DROP ",
            # HTML/Script injection
            "<script",
            "<?php",
            "<%",
        ]

        # For strings under 10KB, check the entire content
        if len(value) < 10000:
            return any(indicator in value for indicator in code_indicators)

        # For longer strings, sample at strategic positions
        sample_positions = [
            0,  # Start
            len(value) // 4,  # 25%
            len(value) // 2,  # 50%
            3 * len(value) // 4,  # 75%
            max(0, len(value) - 2000),  # Near end
        ]

        for pos in sample_positions:
            chunk = value[pos : pos + 2000]
            if any(indicator in chunk for indicator in code_indicators):
                return True

        return False

    def read_all(self) -> dict[str, Any]:
        """Read all accessible data."""
        if self._allowed_read:
            return {k: v for k, v in self._data.items() if k in self._allowed_read}
        return dict(self._data)

    def with_permissions(
        self,
        read_keys: list[str],
        write_keys: list[str],
    ) -> "SharedMemory":
        """Create a view with restricted permissions for a specific node.

        The scoped view shares the same underlying data and locks,
        enabling thread-safe parallel execution across scoped views.
        """
        return SharedMemory(
            _data=self._data,
            _allowed_read=set(read_keys) if read_keys else set(),
            _allowed_write=set(write_keys) if write_keys else set(),
            _lock=self._lock,  # Share lock for thread safety
            _key_locks=self._key_locks,  # Share key locks
        )


__all__ = ["SharedMemory", "MemoryWriteError"]
