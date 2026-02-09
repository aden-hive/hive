"""
Checkpoint Store - Manages checkpoint storage with atomic writes.

Handles saving, loading, listing, and pruning of execution checkpoints
for session resumability.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path

from framework.schemas.checkpoint import Checkpoint, CheckpointIndex, CheckpointSummary
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


class CheckpointStore:
    """
    Manages checkpoint storage with atomic writes.

    Stores checkpoints in a session's checkpoints/ directory with
    an index for fast lookup and filtering.

    Directory structure:
        checkpoints/
            index.json              # Checkpoint manifest
            cp_{type}_{node}_{timestamp}.json  # Individual checkpoints
    """

    def __init__(self, base_path: Path):
        """
        Initialize checkpoint store.

        Args:
            base_path: Session directory (e.g., ~/.hive/agents/agent_name/sessions/session_ID/)
        """
        self.base_path = Path(base_path)
        self.checkpoints_dir = self.base_path / "checkpoints"
        self.index_path = self.checkpoints_dir / "index.json"
        self._index_lock = asyncio.Lock()

    async def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """
        Atomically save checkpoint and update index.

        Uses temp file + rename for crash safety. Updates index
        after checkpoint is persisted.

        Args:
            checkpoint: Checkpoint to save

        Raises:
            OSError: If file write fails
        """

        def _write():
            # Ensure directory exists
            self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

            # Write checkpoint file atomically
            checkpoint_path = self.checkpoints_dir / f"{checkpoint.checkpoint_id}.json"
            with atomic_write(checkpoint_path) as f:
                f.write(checkpoint.model_dump_json(indent=2))

            logger.debug(f"Saved checkpoint {checkpoint.checkpoint_id}")

        # Write checkpoint file (blocking I/O in thread)
        await asyncio.to_thread(_write)

        # Update index (with lock to prevent concurrent modifications)
        async with self._index_lock:
            await self._update_index_add(checkpoint)

    async def load_checkpoint(
        self,
        checkpoint_id: str | None = None,
    ) -> Checkpoint | None:
        """
        Load checkpoint by ID or latest.

        Args:
            checkpoint_id: Checkpoint ID to load, or None for latest

        Returns:
            Checkpoint object, or None if not found
        """

        def _read(checkpoint_id: str) -> Checkpoint | None:
            checkpoint_path = self.checkpoints_dir / f"{checkpoint_id}.json"

            if not checkpoint_path.exists():
                logger.warning(f"Checkpoint file not found: {checkpoint_path}")
                return None

            try:
                return Checkpoint.model_validate_json(checkpoint_path.read_text())
            except Exception as e:
                logger.error(f"Failed to load checkpoint {checkpoint_id}: {e}")
                return None

        # Load index to get checkpoint ID if not provided
        if checkpoint_id is None:
            index = await self.load_index()
            if not index or not index.latest_checkpoint_id:
                logger.warning("No checkpoints found in index")
                return None
            checkpoint_id = index.latest_checkpoint_id

        return await asyncio.to_thread(_read, checkpoint_id)

    async def load_index(self) -> CheckpointIndex | None:
        """
        Load checkpoint index.

        Returns:
            CheckpointIndex or None if not found
        """

        def _read() -> CheckpointIndex | None:
            if not self.index_path.exists():
                return None

            try:
                return CheckpointIndex.model_validate_json(self.index_path.read_text())
            except Exception as e:
                logger.error(f"Failed to load checkpoint index: {e}")
                return None

        return await asyncio.to_thread(_read)

    async def list_checkpoints(
        self,
        checkpoint_type: str | None = None,
        is_clean: bool | None = None,
    ) -> list[CheckpointSummary]:
        """
        List checkpoints with optional filters.

        Args:
            checkpoint_type: Filter by type (node_start, node_complete)
            is_clean: Filter by clean status

        Returns:
            List of CheckpointSummary objects
        """
        index = await self.load_index()
        if not index:
            return []

        checkpoints = index.checkpoints

        # Apply filters
        if checkpoint_type:
            checkpoints = [cp for cp in checkpoints if cp.checkpoint_type == checkpoint_type]

        if is_clean is not None:
            checkpoints = [cp for cp in checkpoints if cp.is_clean == is_clean]

        return checkpoints

    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Delete a specific checkpoint.

        Args:
            checkpoint_id: Checkpoint ID to delete

        Returns:
            True if deleted, False if not found
        """

        def _delete(checkpoint_id: str) -> bool:
            checkpoint_path = self.checkpoints_dir / f"{checkpoint_id}.json"

            if not checkpoint_path.exists():
                logger.warning(f"Checkpoint file not found: {checkpoint_path}")
                return False

            try:
                checkpoint_path.unlink()
                logger.info(f"Deleted checkpoint {checkpoint_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete checkpoint {checkpoint_id}: {e}")
                return False

        # Delete checkpoint file
        deleted = await asyncio.to_thread(_delete, checkpoint_id)

        if deleted:
            # Update index (with lock)
            async with self._index_lock:
                await self._update_index_remove(checkpoint_id)

        return deleted

    async def prune_checkpoints(
        self,
        max_age_days: int = 7,
    ) -> int:
        """
        Prune checkpoints older than max_age_days.

        Args:
            max_age_days: Maximum age in days (default 7)

        Returns:
            Number of checkpoints deleted
        """
        index = await self.load_index()
        if not index or not index.checkpoints:
            return 0

        # Calculate cutoff datetime
        cutoff = datetime.now() - timedelta(days=max_age_days)

        # Find old checkpoints
        old_checkpoints = []
        for cp in index.checkpoints:
            try:
                created = datetime.fromisoformat(cp.created_at)
                if created < cutoff:
                    old_checkpoints.append(cp.checkpoint_id)
            except Exception as e:
                logger.warning(f"Failed to parse timestamp for {cp.checkpoint_id}: {e}")

        # Delete old checkpoints
        deleted_count = 0
        for checkpoint_id in old_checkpoints:
            if await self.delete_checkpoint(checkpoint_id):
                deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Pruned {deleted_count} checkpoints older than {max_age_days} days")

        return deleted_count

    async def checkpoint_exists(self, checkpoint_id: str) -> bool:
        """
        Check if a checkpoint exists.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            True if checkpoint exists
        """

        def _check(checkpoint_id: str) -> bool:
            checkpoint_path = self.checkpoints_dir / f"{checkpoint_id}.json"
            return checkpoint_path.exists()

        return await asyncio.to_thread(_check, checkpoint_id)

    async def _update_index_add(self, checkpoint: Checkpoint) -> None:
        """
        Update index after adding a checkpoint.

        Should be called with _index_lock held.

        Args:
            checkpoint: Checkpoint that was added
        """

        def _write(index: CheckpointIndex):
            # Ensure directory exists
            self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

            # Write index atomically
            with atomic_write(self.index_path) as f:
                f.write(index.model_dump_json(indent=2))

        # Load or create index
        index = await self.load_index()
        if not index:
            index = CheckpointIndex(
                session_id=checkpoint.session_id,
                checkpoints=[],
            )

        # Add checkpoint to index
        index.add_checkpoint(checkpoint)

        # Write updated index
        await asyncio.to_thread(_write, index)

        logger.debug(f"Updated index with checkpoint {checkpoint.checkpoint_id}")

    async def _update_index_remove(self, checkpoint_id: str) -> None:
        """
        Update index after removing a checkpoint.

        Should be called with _index_lock held.

        Args:
            checkpoint_id: Checkpoint ID that was removed
        """

        def _write(index: CheckpointIndex):
            with atomic_write(self.index_path) as f:
                f.write(index.model_dump_json(indent=2))

        # Load index
        index = await self.load_index()
        if not index:
            return

        # Remove checkpoint from index
        index.checkpoints = [cp for cp in index.checkpoints if cp.checkpoint_id != checkpoint_id]

        # Update totals
        index.total_checkpoints = len(index.checkpoints)

        # Update latest_checkpoint_id if we removed the latest
        if index.latest_checkpoint_id == checkpoint_id:
            index.latest_checkpoint_id = (
                index.checkpoints[-1].checkpoint_id if index.checkpoints else None
            )

        # Write updated index
        await asyncio.to_thread(_write, index)

        logger.debug(f"Removed checkpoint {checkpoint_id} from index")
