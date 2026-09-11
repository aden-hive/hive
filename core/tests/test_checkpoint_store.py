"""Tests for checkpoint storage behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from framework.schemas.checkpoint import Checkpoint
from framework.storage.checkpoint_store import CheckpointStore


def _make_checkpoint(
    checkpoint_id: str,
    *,
    checkpoint_type: str = "node_start",
    session_id: str = "session-1",
    created_at: str | None = None,
    current_node: str = "node-a",
    is_clean: bool = True,
) -> Checkpoint:
    return Checkpoint(
        checkpoint_id=checkpoint_id,
        checkpoint_type=checkpoint_type,
        session_id=session_id,
        created_at=created_at or datetime.now().isoformat(),
        current_node=current_node,
        next_node=None,
        execution_path=[current_node],
        shared_memory={"k": "v"},
        accumulated_outputs={},
        metrics_snapshot={},
        is_clean=is_clean,
        description=f"{checkpoint_type} for {current_node}",
    )


@pytest.fixture
def store(tmp_path: Path) -> CheckpointStore:
    return CheckpointStore(tmp_path)


class TestCheckpointStoreSaveLoad:
    @pytest.mark.asyncio
    async def test_save_checkpoint_writes_file_and_index(self, store: CheckpointStore):
        checkpoint = _make_checkpoint("cp_node_start_node_a_1")

        await store.save_checkpoint(checkpoint)

        checkpoint_path = store.checkpoints_dir / f"{checkpoint.checkpoint_id}.json"
        assert checkpoint_path.exists()
        index = await store.load_index()
        assert index is not None
        assert index.total_checkpoints == 1
        assert index.latest_checkpoint_id == checkpoint.checkpoint_id

    @pytest.mark.asyncio
    async def test_save_checkpoint_updates_latest_checkpoint_when_saving_multiple(
        self,
        store: CheckpointStore,
    ):
        first = _make_checkpoint("cp_node_start_node_a_1")
        second = _make_checkpoint("cp_node_complete_node_a_2", checkpoint_type="node_complete")

        await store.save_checkpoint(first)
        await store.save_checkpoint(second)

        index = await store.load_index()
        assert index is not None
        assert index.total_checkpoints == 2
        assert index.latest_checkpoint_id == second.checkpoint_id

    @pytest.mark.asyncio
    async def test_load_checkpoint_by_id_returns_checkpoint(self, store: CheckpointStore):
        checkpoint = _make_checkpoint("cp_node_start_node_b_1", current_node="node-b")
        await store.save_checkpoint(checkpoint)

        loaded = await store.load_checkpoint(checkpoint.checkpoint_id)

        assert loaded is not None
        assert loaded.checkpoint_id == checkpoint.checkpoint_id
        assert loaded.current_node == "node-b"

    @pytest.mark.asyncio
    async def test_load_checkpoint_without_id_returns_latest(self, store: CheckpointStore):
        first = _make_checkpoint("cp_node_start_node_a_1")
        second = _make_checkpoint("cp_node_start_node_c_2", current_node="node-c")
        await store.save_checkpoint(first)
        await store.save_checkpoint(second)

        loaded = await store.load_checkpoint()

        assert loaded is not None
        assert loaded.checkpoint_id == second.checkpoint_id

    @pytest.mark.asyncio
    async def test_load_checkpoint_without_index_returns_none(self, store: CheckpointStore):
        loaded = await store.load_checkpoint()

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_checkpoint_missing_file_returns_none(self, store: CheckpointStore):
        loaded = await store.load_checkpoint("does_not_exist")

        assert loaded is None

    @pytest.mark.asyncio
    async def test_load_checkpoint_with_corrupt_json_returns_none(self, store: CheckpointStore):
        checkpoint = _make_checkpoint("cp_node_start_node_a_1")
        await store.save_checkpoint(checkpoint)
        checkpoint_path = store.checkpoints_dir / f"{checkpoint.checkpoint_id}.json"
        checkpoint_path.write_text("{bad json", encoding="utf-8")

        loaded = await store.load_checkpoint(checkpoint.checkpoint_id)

        assert loaded is None


class TestCheckpointStoreListAndExists:
    @pytest.mark.asyncio
    async def test_list_checkpoints_returns_empty_when_index_missing(self, store: CheckpointStore):
        checkpoints = await store.list_checkpoints()

        assert checkpoints == []

    @pytest.mark.asyncio
    async def test_list_checkpoints_returns_all_checkpoints(self, store: CheckpointStore):
        a = _make_checkpoint("cp_node_start_node_a_1")
        b = _make_checkpoint("cp_node_complete_node_a_2", checkpoint_type="node_complete")
        await store.save_checkpoint(a)
        await store.save_checkpoint(b)

        checkpoints = await store.list_checkpoints()

        assert len(checkpoints) == 2
        assert [cp.checkpoint_id for cp in checkpoints] == [a.checkpoint_id, b.checkpoint_id]

    @pytest.mark.asyncio
    async def test_list_checkpoints_filters_by_type(self, store: CheckpointStore):
        a = _make_checkpoint("cp_node_start_node_a_1", checkpoint_type="node_start")
        b = _make_checkpoint("cp_node_complete_node_a_2", checkpoint_type="node_complete")
        await store.save_checkpoint(a)
        await store.save_checkpoint(b)

        checkpoints = await store.list_checkpoints(checkpoint_type="node_complete")

        assert len(checkpoints) == 1
        assert checkpoints[0].checkpoint_id == b.checkpoint_id

    @pytest.mark.asyncio
    async def test_list_checkpoints_filters_by_clean_status(self, store: CheckpointStore):
        clean = _make_checkpoint("cp_clean_1", is_clean=True)
        dirty = _make_checkpoint("cp_dirty_1", is_clean=False)
        await store.save_checkpoint(clean)
        await store.save_checkpoint(dirty)

        clean_checkpoints = await store.list_checkpoints(is_clean=True)
        dirty_checkpoints = await store.list_checkpoints(is_clean=False)

        assert [cp.checkpoint_id for cp in clean_checkpoints] == [clean.checkpoint_id]
        assert [cp.checkpoint_id for cp in dirty_checkpoints] == [dirty.checkpoint_id]

    @pytest.mark.asyncio
    async def test_checkpoint_exists_true_when_file_present(self, store: CheckpointStore):
        checkpoint = _make_checkpoint("cp_exists_1")
        await store.save_checkpoint(checkpoint)

        exists = await store.checkpoint_exists(checkpoint.checkpoint_id)

        assert exists is True

    @pytest.mark.asyncio
    async def test_checkpoint_exists_false_for_missing_file(self, store: CheckpointStore):
        exists = await store.checkpoint_exists("missing_checkpoint")

        assert exists is False


class TestCheckpointStoreDelete:
    @pytest.mark.asyncio
    async def test_delete_checkpoint_removes_file_and_index_entry(self, store: CheckpointStore):
        checkpoint = _make_checkpoint("cp_delete_1")
        await store.save_checkpoint(checkpoint)

        deleted = await store.delete_checkpoint(checkpoint.checkpoint_id)

        assert deleted is True
        assert not (store.checkpoints_dir / f"{checkpoint.checkpoint_id}.json").exists()
        index = await store.load_index()
        assert index is not None
        assert index.total_checkpoints == 0

    @pytest.mark.asyncio
    async def test_delete_checkpoint_updates_latest_when_deleting_latest(
        self,
        store: CheckpointStore,
    ):
        first = _make_checkpoint("cp_keep_1")
        latest = _make_checkpoint("cp_latest_2")
        await store.save_checkpoint(first)
        await store.save_checkpoint(latest)

        deleted = await store.delete_checkpoint(latest.checkpoint_id)

        assert deleted is True
        index = await store.load_index()
        assert index is not None
        assert index.latest_checkpoint_id == first.checkpoint_id
        assert index.total_checkpoints == 1

    @pytest.mark.asyncio
    async def test_delete_checkpoint_clears_latest_when_last_removed(self, store: CheckpointStore):
        checkpoint = _make_checkpoint("cp_last_1")
        await store.save_checkpoint(checkpoint)

        deleted = await store.delete_checkpoint(checkpoint.checkpoint_id)

        assert deleted is True
        index = await store.load_index()
        assert index is not None
        assert index.latest_checkpoint_id is None
        assert index.total_checkpoints == 0

    @pytest.mark.asyncio
    async def test_delete_checkpoint_returns_false_when_file_missing(self, store: CheckpointStore):
        deleted = await store.delete_checkpoint("missing_checkpoint")

        assert deleted is False


class TestCheckpointStorePrune:
    @pytest.mark.asyncio
    async def test_prune_checkpoints_returns_zero_without_index(self, store: CheckpointStore):
        deleted_count = await store.prune_checkpoints(max_age_days=7)

        assert deleted_count == 0

    @pytest.mark.asyncio
    async def test_prune_checkpoints_deletes_only_old_checkpoints(self, store: CheckpointStore):
        old_created = (datetime.now() - timedelta(days=10)).isoformat()
        new_created = (datetime.now() - timedelta(days=1)).isoformat()
        old_checkpoint = _make_checkpoint("cp_old_1", created_at=old_created)
        new_checkpoint = _make_checkpoint("cp_new_1", created_at=new_created)
        await store.save_checkpoint(old_checkpoint)
        await store.save_checkpoint(new_checkpoint)

        deleted_count = await store.prune_checkpoints(max_age_days=7)

        assert deleted_count == 1
        assert await store.checkpoint_exists(old_checkpoint.checkpoint_id) is False
        assert await store.checkpoint_exists(new_checkpoint.checkpoint_id) is True

    @pytest.mark.asyncio
    async def test_prune_checkpoints_skips_invalid_timestamp_entries(self, store: CheckpointStore):
        invalid_checkpoint = _make_checkpoint("cp_invalid_1", created_at="not-a-date")
        old_created = (datetime.now() - timedelta(days=30)).isoformat()
        old_checkpoint = _make_checkpoint("cp_old_2", created_at=old_created)
        await store.save_checkpoint(invalid_checkpoint)
        await store.save_checkpoint(old_checkpoint)

        deleted_count = await store.prune_checkpoints(max_age_days=7)

        assert deleted_count == 1
        assert await store.checkpoint_exists(old_checkpoint.checkpoint_id) is False
        assert await store.checkpoint_exists(invalid_checkpoint.checkpoint_id) is True
