"""Tests for CheckpointStore - filesystem-backed checkpoint persistence.

Covers save/load roundtrip, listing with filters, delete, exists,
prune by age, and error cases for missing or invalid data.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from framework.schemas.checkpoint import Checkpoint, CheckpointIndex
from framework.storage.checkpoint_store import CheckpointStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_checkpoint(
    *,
    checkpoint_type: str = "node_start",
    session_id: str = "session_abc",
    run_id: str = "run_123",
    current_node: str = "node_A",
    data_buffer: dict[str, Any] | None = None,
    is_clean: bool = True,
    created_at: str | None = None,
    checkpoint_id: str | None = None,
) -> Checkpoint:
    """Build a Checkpoint instance with sensible defaults for tests."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cp_id = checkpoint_id or f"cp_{checkpoint_type}_{current_node}_{ts}"
    return Checkpoint(
        checkpoint_id=cp_id,
        checkpoint_type=checkpoint_type,
        session_id=session_id,
        run_id=run_id,
        created_at=created_at or datetime.now().isoformat(),
        current_node=current_node,
        execution_path=[current_node],
        data_buffer=data_buffer or {"key": "value"},
        is_clean=is_clean,
        description=f"Test checkpoint for {current_node}",
    )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------


class TestCheckpointStoreInit:
    """Verify the store is configured correctly on construction."""

    def test_paths_derived_from_base(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        assert store.base_path == tmp_path
        assert store.checkpoints_dir == tmp_path / "checkpoints"
        assert store.index_path == tmp_path / "checkpoints" / "index.json"

    def test_accepts_string_path(self, tmp_path: Path):
        """Constructor should coerce a string path to Path."""
        store = CheckpointStore(str(tmp_path))
        assert isinstance(store.base_path, Path)


# ---------------------------------------------------------------------------
# save_checkpoint / load_checkpoint roundtrip
# ---------------------------------------------------------------------------


class TestSaveLoadRoundtrip:
    """Data integrity: loaded checkpoint must equal the saved one."""

    @pytest.mark.asyncio
    async def test_basic_roundtrip(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)
        loaded = await store.load_checkpoint(cp.checkpoint_id)

        assert loaded is not None
        assert loaded.checkpoint_id == cp.checkpoint_id
        assert loaded.checkpoint_type == cp.checkpoint_type
        assert loaded.session_id == cp.session_id
        assert loaded.run_id == cp.run_id
        assert loaded.current_node == cp.current_node
        assert loaded.data_buffer == cp.data_buffer
        assert loaded.is_clean == cp.is_clean

    @pytest.mark.asyncio
    async def test_data_buffer_preserved(self, tmp_path: Path):
        """Nested data_buffer contents survive serialization."""
        store = CheckpointStore(tmp_path)
        nested = {"outer": {"inner": [1, 2, 3]}, "flag": True, "count": 42}
        cp = make_checkpoint(data_buffer=nested)

        await store.save_checkpoint(cp)
        loaded = await store.load_checkpoint(cp.checkpoint_id)

        assert loaded is not None
        assert loaded.data_buffer == nested

    @pytest.mark.asyncio
    async def test_checkpoint_file_created_on_disk(self, tmp_path: Path):
        """Saving a checkpoint must create the JSON file on disk."""
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)

        expected_path = tmp_path / "checkpoints" / f"{cp.checkpoint_id}.json"
        assert expected_path.exists()
        assert expected_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_index_file_created_on_save(self, tmp_path: Path):
        """Saving a checkpoint must also create the index file."""
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)

        assert (tmp_path / "checkpoints" / "index.json").exists()

    @pytest.mark.asyncio
    async def test_index_tracks_latest_after_multiple_saves(self, tmp_path: Path):
        """latest_checkpoint_id in the index should point to the most recently saved checkpoint."""
        store = CheckpointStore(tmp_path)
        cp1 = make_checkpoint(checkpoint_id="cp_first", current_node="node_A")
        cp2 = make_checkpoint(checkpoint_id="cp_second", current_node="node_B")

        await store.save_checkpoint(cp1)
        await store.save_checkpoint(cp2)

        index = await store.load_index()
        assert index is not None
        assert index.latest_checkpoint_id == "cp_second"

    @pytest.mark.asyncio
    async def test_load_latest_without_id(self, tmp_path: Path):
        """Calling load_checkpoint(None) should return the latest checkpoint."""
        store = CheckpointStore(tmp_path)
        cp1 = make_checkpoint(checkpoint_id="cp_first")
        cp2 = make_checkpoint(checkpoint_id="cp_second")

        await store.save_checkpoint(cp1)
        await store.save_checkpoint(cp2)

        latest = await store.load_checkpoint()  # no ID → latest
        assert latest is not None
        assert latest.checkpoint_id == "cp_second"


# ---------------------------------------------------------------------------
# list_checkpoints
# ---------------------------------------------------------------------------


class TestListCheckpoints:
    """Listing and filtering of checkpoints via the index."""

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_checkpoints(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        result = await store.list_checkpoints()

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_all_checkpoints(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp1 = make_checkpoint(checkpoint_id="cp_1", checkpoint_type="node_start")
        cp2 = make_checkpoint(checkpoint_id="cp_2", checkpoint_type="node_complete")

        await store.save_checkpoint(cp1)
        await store.save_checkpoint(cp2)

        result = await store.list_checkpoints()

        ids = {cp.checkpoint_id for cp in result}
        assert ids == {"cp_1", "cp_2"}

    @pytest.mark.asyncio
    async def test_filter_by_checkpoint_type(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_ns", checkpoint_type="node_start")
        )
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_nc", checkpoint_type="node_complete")
        )
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_li", checkpoint_type="loop_iteration")
        )

        result = await store.list_checkpoints(checkpoint_type="node_start")

        assert len(result) == 1
        assert result[0].checkpoint_id == "cp_ns"

    @pytest.mark.asyncio
    async def test_filter_by_is_clean_true(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        await store.save_checkpoint(make_checkpoint(checkpoint_id="cp_clean", is_clean=True))
        await store.save_checkpoint(make_checkpoint(checkpoint_id="cp_dirty", is_clean=False))

        result = await store.list_checkpoints(is_clean=True)

        assert all(cp.is_clean for cp in result)
        ids = {cp.checkpoint_id for cp in result}
        assert "cp_clean" in ids
        assert "cp_dirty" not in ids

    @pytest.mark.asyncio
    async def test_filter_by_is_clean_false(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        await store.save_checkpoint(make_checkpoint(checkpoint_id="cp_clean", is_clean=True))
        await store.save_checkpoint(make_checkpoint(checkpoint_id="cp_dirty", is_clean=False))

        result = await store.list_checkpoints(is_clean=False)

        assert len(result) == 1
        assert result[0].checkpoint_id == "cp_dirty"

    @pytest.mark.asyncio
    async def test_combined_type_and_clean_filter(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_a", checkpoint_type="node_start", is_clean=True)
        )
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_b", checkpoint_type="node_start", is_clean=False)
        )
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_c", checkpoint_type="node_complete", is_clean=True)
        )

        result = await store.list_checkpoints(checkpoint_type="node_start", is_clean=True)

        assert len(result) == 1
        assert result[0].checkpoint_id == "cp_a"


# ---------------------------------------------------------------------------
# checkpoint_exists
# ---------------------------------------------------------------------------


class TestCheckpointExists:
    """Existence checks for saved and unsaved checkpoints."""

    @pytest.mark.asyncio
    async def test_returns_true_after_save(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)

        assert await store.checkpoint_exists(cp.checkpoint_id) is True

    @pytest.mark.asyncio
    async def test_returns_false_for_unknown_id(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        assert await store.checkpoint_exists("cp_nonexistent") is False

    @pytest.mark.asyncio
    async def test_returns_false_after_delete(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)
        await store.delete_checkpoint(cp.checkpoint_id)

        assert await store.checkpoint_exists(cp.checkpoint_id) is False


# ---------------------------------------------------------------------------
# delete_checkpoint
# ---------------------------------------------------------------------------


class TestDeleteCheckpoint:
    """Deletion behaviour including index updates."""

    @pytest.mark.asyncio
    async def test_delete_returns_true_for_existing(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)
        result = await store.delete_checkpoint(cp.checkpoint_id)

        assert result is True

    @pytest.mark.asyncio
    async def test_delete_removes_file_from_disk(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()
        await store.save_checkpoint(cp)

        await store.delete_checkpoint(cp.checkpoint_id)

        file_path = tmp_path / "checkpoints" / f"{cp.checkpoint_id}.json"
        assert not file_path.exists()

    @pytest.mark.asyncio
    async def test_delete_returns_false_for_nonexistent(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        result = await store.delete_checkpoint("cp_does_not_exist")

        assert result is False

    @pytest.mark.asyncio
    async def test_delete_removes_from_index(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()
        await store.save_checkpoint(cp)

        await store.delete_checkpoint(cp.checkpoint_id)

        index = await store.load_index()
        assert index is not None
        assert all(c.checkpoint_id != cp.checkpoint_id for c in index.checkpoints)

    @pytest.mark.asyncio
    async def test_delete_updates_latest_checkpoint_id(self, tmp_path: Path):
        """Deleting the latest checkpoint should promote the previous one."""
        store = CheckpointStore(tmp_path)
        cp1 = make_checkpoint(checkpoint_id="cp_first")
        cp2 = make_checkpoint(checkpoint_id="cp_second")

        await store.save_checkpoint(cp1)
        await store.save_checkpoint(cp2)

        await store.delete_checkpoint("cp_second")

        index = await store.load_index()
        assert index is not None
        assert index.latest_checkpoint_id == "cp_first"

    @pytest.mark.asyncio
    async def test_delete_last_checkpoint_clears_latest(self, tmp_path: Path):
        """Deleting the only checkpoint sets latest_checkpoint_id to None."""
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()
        await store.save_checkpoint(cp)

        await store.delete_checkpoint(cp.checkpoint_id)

        index = await store.load_index()
        assert index is not None
        assert index.latest_checkpoint_id is None


# ---------------------------------------------------------------------------
# prune_checkpoints
# ---------------------------------------------------------------------------


class TestPruneCheckpoints:
    """TTL-based pruning of old checkpoints."""

    @pytest.mark.asyncio
    async def test_prune_returns_zero_when_no_checkpoints(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        deleted = await store.prune_checkpoints(max_age_days=7)

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_prune_removes_old_checkpoints(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        # Create a checkpoint with a timestamp 10 days in the past
        old_ts = (datetime.now() - timedelta(days=10)).isoformat()
        old_cp = make_checkpoint(checkpoint_id="cp_old", created_at=old_ts)
        await store.save_checkpoint(old_cp)

        deleted = await store.prune_checkpoints(max_age_days=7)

        assert deleted == 1
        assert await store.checkpoint_exists("cp_old") is False

    @pytest.mark.asyncio
    async def test_prune_keeps_recent_checkpoints(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        # Recent checkpoint (1 day old)
        recent_ts = (datetime.now() - timedelta(days=1)).isoformat()
        recent_cp = make_checkpoint(checkpoint_id="cp_recent", created_at=recent_ts)
        await store.save_checkpoint(recent_cp)

        deleted = await store.prune_checkpoints(max_age_days=7)

        assert deleted == 0
        assert await store.checkpoint_exists("cp_recent") is True

    @pytest.mark.asyncio
    async def test_prune_mixed_ages(self, tmp_path: Path):
        """Only checkpoints exceeding max_age_days should be deleted."""
        store = CheckpointStore(tmp_path)

        old_ts = (datetime.now() - timedelta(days=10)).isoformat()
        recent_ts = (datetime.now() - timedelta(days=2)).isoformat()

        await store.save_checkpoint(make_checkpoint(checkpoint_id="cp_old", created_at=old_ts))
        await store.save_checkpoint(
            make_checkpoint(checkpoint_id="cp_recent", created_at=recent_ts)
        )

        deleted = await store.prune_checkpoints(max_age_days=7)

        assert deleted == 1
        assert await store.checkpoint_exists("cp_old") is False
        assert await store.checkpoint_exists("cp_recent") is True

    @pytest.mark.asyncio
    async def test_prune_updates_index(self, tmp_path: Path):
        """After pruning, the index must not contain pruned checkpoint IDs."""
        store = CheckpointStore(tmp_path)

        old_ts = (datetime.now() - timedelta(days=15)).isoformat()
        old_cp = make_checkpoint(checkpoint_id="cp_old", created_at=old_ts)
        await store.save_checkpoint(old_cp)

        await store.prune_checkpoints(max_age_days=7)

        index = await store.load_index()
        assert index is not None
        ids_in_index = {cp.checkpoint_id for cp in index.checkpoints}
        assert "cp_old" not in ids_in_index


# ---------------------------------------------------------------------------
# load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    """Behaviour of the index loader under normal and edge-case conditions."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_index(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        index = await store.load_index()

        assert index is None

    @pytest.mark.asyncio
    async def test_returns_checkpoint_index_after_save(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        cp = make_checkpoint()
        await store.save_checkpoint(cp)

        index = await store.load_index()

        assert isinstance(index, CheckpointIndex)
        assert index.session_id == cp.session_id
        assert index.total_checkpoints == 1

    @pytest.mark.asyncio
    async def test_index_is_invalid_json_returns_none(self, tmp_path: Path):
        """Corrupt index file must not raise — it must return None and log error."""
        store = CheckpointStore(tmp_path)
        store.checkpoints_dir.mkdir(parents=True, exist_ok=True)
        store.index_path.write_text("{{not valid json}}", encoding="utf-8")

        index = await store.load_index()

        assert index is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    """Edge cases: missing files, empty store, non-existent IDs."""

    @pytest.mark.asyncio
    async def test_load_nonexistent_checkpoint_returns_none(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        loaded = await store.load_checkpoint("cp_does_not_exist")

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_latest_with_empty_index_returns_none(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)

        loaded = await store.load_checkpoint()

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_corrupted_checkpoint_file_returns_none(self, tmp_path: Path):
        """A checkpoint file with invalid JSON must return None, not raise."""
        store = CheckpointStore(tmp_path)
        # Save a valid checkpoint first so the index knows about it
        cp = make_checkpoint(checkpoint_id="cp_corrupt")
        await store.save_checkpoint(cp)

        # Overwrite the checkpoint file with garbage
        corrupt_path = tmp_path / "checkpoints" / "cp_corrupt.json"
        corrupt_path.write_text("!!!invalid json!!!", encoding="utf-8")

        loaded = await store.load_checkpoint("cp_corrupt")

        assert loaded is None

    @pytest.mark.asyncio
    async def test_list_with_no_matching_type_returns_empty(self, tmp_path: Path):
        store = CheckpointStore(tmp_path)
        await store.save_checkpoint(make_checkpoint(checkpoint_type="node_start"))

        result = await store.list_checkpoints(checkpoint_type="loop_iteration")

        assert result == []

    @pytest.mark.asyncio
    async def test_save_creates_directory_automatically(self, tmp_path: Path):
        """Saving into a non-existent subdirectory must succeed."""
        nested = tmp_path / "deep" / "nested" / "session"
        store = CheckpointStore(nested)
        cp = make_checkpoint()

        await store.save_checkpoint(cp)

        assert (nested / "checkpoints" / f"{cp.checkpoint_id}.json").exists()
