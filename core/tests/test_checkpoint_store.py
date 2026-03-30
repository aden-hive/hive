"""Tests for CheckpointStore - save, load, list, delete, and prune operations."""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from framework.schemas.checkpoint import Checkpoint
from framework.storage.checkpoint_store import CheckpointStore

# === HELPER ===


def make_checkpoint(
    session_id: str = "session_abc",
    checkpoint_type: str = "node_complete",
    current_node: str = "node_1",
    is_clean: bool = True,
) -> Checkpoint:
    """Build a minimal valid Checkpoint for use in tests."""
    return Checkpoint.create(
        checkpoint_type=checkpoint_type,
        session_id=session_id,
        current_node=current_node,
        execution_path=[current_node],
        shared_memory={"key": "value"},
        is_clean=is_clean,
    )


# === SAVE AND LOAD ===


class TestSaveAndLoad:
    """Tests for save_checkpoint and load_checkpoint."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, tmp_path: Path):
        """Saving a checkpoint and loading it back should return identical data."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        loaded = await store.load_checkpoint(checkpoint.checkpoint_id)

        assert loaded is not None
        assert loaded.checkpoint_id == checkpoint.checkpoint_id
        assert loaded.session_id == checkpoint.session_id
        assert loaded.checkpoint_type == checkpoint.checkpoint_type
        assert loaded.current_node == checkpoint.current_node
        assert loaded.shared_memory == checkpoint.shared_memory
        assert loaded.execution_path == checkpoint.execution_path
        assert loaded.is_clean == checkpoint.is_clean

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path: Path):
        """Loading a checkpoint ID that was never saved should return None."""
        store = CheckpointStore(tmp_path)

        result = await store.load_checkpoint("cp_does_not_exist")

        assert result is None

    @pytest.mark.asyncio
    async def test_load_latest_returns_most_recent(self, tmp_path: Path):
        """Calling load_checkpoint with no ID should return the latest saved checkpoint."""
        store = CheckpointStore(tmp_path)
        first = make_checkpoint(current_node="node_1")
        second = make_checkpoint(current_node="node_2")

        await store.save_checkpoint(first)
        await store.save_checkpoint(second)
        loaded = await store.load_checkpoint()

        assert loaded is not None
        assert loaded.checkpoint_id == second.checkpoint_id

    @pytest.mark.asyncio
    async def test_load_latest_on_empty_store_returns_none(self, tmp_path: Path):
        """Calling load_checkpoint with no ID on an empty store should return None."""
        store = CheckpointStore(tmp_path)

        result = await store.load_checkpoint()

        assert result is None

    @pytest.mark.asyncio
    async def test_save_creates_checkpoint_file_on_disk(self, tmp_path: Path):
        """Saving a checkpoint should create a physical JSON file in checkpoints/."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)

        expected_file = tmp_path / "checkpoints" / f"{checkpoint.checkpoint_id}.json"
        assert expected_file.exists()

    @pytest.mark.asyncio
    async def test_save_preserves_shared_memory(self, tmp_path: Path):
        """Complex shared memory data should survive a save/load roundtrip."""
        store = CheckpointStore(tmp_path)
        checkpoint = Checkpoint.create(
            checkpoint_type="node_complete",
            session_id="session_abc",
            current_node="node_1",
            execution_path=["node_1"],
            shared_memory={"nested": {"count": 42, "items": [1, 2, 3]}, "flag": True},
        )

        await store.save_checkpoint(checkpoint)
        loaded = await store.load_checkpoint(checkpoint.checkpoint_id)

        assert loaded.shared_memory == checkpoint.shared_memory


# === LIST ===


class TestListCheckpoints:
    """Tests for list_checkpoints."""

    @pytest.mark.asyncio
    async def test_list_returns_all_saved_checkpoints(self, tmp_path: Path):
        """Saving three checkpoints should return all three when listed."""
        store = CheckpointStore(tmp_path)
        checkpoints = [make_checkpoint(current_node=f"node_{i}") for i in range(3)]

        for cp in checkpoints:
            await store.save_checkpoint(cp)

        listed = await store.list_checkpoints()

        assert len(listed) == 3

    @pytest.mark.asyncio
    async def test_list_on_empty_store_returns_empty_list(self, tmp_path: Path):
        """Listing checkpoints on a fresh store should return an empty list."""
        store = CheckpointStore(tmp_path)

        result = await store.list_checkpoints()

        assert result == []

    @pytest.mark.asyncio
    async def test_list_filter_by_type(self, tmp_path: Path):
        """Filtering by checkpoint_type should return only matching checkpoints."""
        store = CheckpointStore(tmp_path)
        start_cp = make_checkpoint(checkpoint_type="node_start")
        complete_cp = make_checkpoint(checkpoint_type="node_complete", current_node="node_2")

        await store.save_checkpoint(start_cp)
        await store.save_checkpoint(complete_cp)

        result = await store.list_checkpoints(checkpoint_type="node_start")

        assert len(result) == 1
        assert result[0].checkpoint_type == "node_start"

    @pytest.mark.asyncio
    async def test_list_filter_by_is_clean(self, tmp_path: Path):
        """Filtering by is_clean should return only matching checkpoints."""
        store = CheckpointStore(tmp_path)
        clean_cp = make_checkpoint(is_clean=True)
        dirty_cp = make_checkpoint(is_clean=False, current_node="node_2")

        await store.save_checkpoint(clean_cp)
        await store.save_checkpoint(dirty_cp)

        result = await store.list_checkpoints(is_clean=True)

        assert len(result) == 1
        assert result[0].is_clean is True


# === DELETE ===


class TestDeleteCheckpoint:
    """Tests for delete_checkpoint."""

    @pytest.mark.asyncio
    async def test_delete_existing_checkpoint_returns_true(self, tmp_path: Path):
        """Deleting a saved checkpoint should return True."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        result = await store.delete_checkpoint(checkpoint.checkpoint_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_removes_file_from_disk(self, tmp_path: Path):
        """After deletion the checkpoint file should no longer exist on disk."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        await store.delete_checkpoint(checkpoint.checkpoint_id)

        file_path = tmp_path / "checkpoints" / f"{checkpoint.checkpoint_id}.json"
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_removes_checkpoint_from_list(self, tmp_path: Path):
        """After deletion the checkpoint should no longer appear in list_checkpoints."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        await store.delete_checkpoint(checkpoint.checkpoint_id)
        listed = await store.list_checkpoints()

        assert all(cp.checkpoint_id != checkpoint.checkpoint_id for cp in listed)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, tmp_path: Path):
        """Deleting a checkpoint ID that doesn't exist should return False without crashing."""
        store = CheckpointStore(tmp_path)

        result = await store.delete_checkpoint("cp_never_existed")

        assert result is False


# === CHECKPOINT EXISTS ===


class TestCheckpointExists:
    """Tests for checkpoint_exists."""

    @pytest.mark.asyncio
    async def test_exists_returns_true_after_save(self, tmp_path: Path):
        """checkpoint_exists should return True for a saved checkpoint."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        result = await store.checkpoint_exists(checkpoint.checkpoint_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_unknown_id(self, tmp_path: Path):
        """checkpoint_exists should return False for an ID that was never saved."""
        store = CheckpointStore(tmp_path)

        result = await store.checkpoint_exists("cp_unknown")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_returns_false_after_delete(self, tmp_path: Path):
        """checkpoint_exists should return False after a checkpoint is deleted."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        await store.delete_checkpoint(checkpoint.checkpoint_id)
        result = await store.checkpoint_exists(checkpoint.checkpoint_id)

        assert result is False


# === PRUNE ===


class TestPruneCheckpoints:
    """Tests for prune_checkpoints."""

    @pytest.mark.asyncio
    async def test_prune_removes_old_checkpoints(self, tmp_path: Path):
        """Checkpoints older than max_age_days should be deleted by prune."""
        store = CheckpointStore(tmp_path)
        old_cp = make_checkpoint(current_node="old_node")

        await store.save_checkpoint(old_cp)

        # Backdate the checkpoint's created_at directly in the index
        index = await store.load_index()
        for summary in index.checkpoints:
            if summary.checkpoint_id == old_cp.checkpoint_id:
                summary.created_at = (datetime.now() - timedelta(days=10)).isoformat()
        from framework.utils.io import atomic_write

        with atomic_write(store.index_path) as f:
            f.write(index.model_dump_json(indent=2))

        deleted_count = await store.prune_checkpoints(max_age_days=7)

        assert deleted_count == 1

    @pytest.mark.asyncio
    async def test_prune_keeps_recent_checkpoints(self, tmp_path: Path):
        """Checkpoints newer than max_age_days should not be pruned."""
        store = CheckpointStore(tmp_path)
        checkpoint = make_checkpoint()

        await store.save_checkpoint(checkpoint)
        deleted_count = await store.prune_checkpoints(max_age_days=7)

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_prune_on_empty_store_returns_zero(self, tmp_path: Path):
        """Pruning an empty store should return 0 without errors."""
        store = CheckpointStore(tmp_path)

        result = await store.prune_checkpoints()

        assert result == 0
