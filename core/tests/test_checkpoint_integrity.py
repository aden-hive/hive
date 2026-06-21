import pytest
import json
from pathlib import Path
from framework.storage.checkpoint_store import CheckpointStore, CheckpointCorruptionError
from framework.schemas.checkpoint import Checkpoint, CheckpointIndex


@pytest.mark.asyncio
async def test_load_valid_checkpoint(tmp_path):
    # Setup CheckpointStore
    store = CheckpointStore(base_path=tmp_path)
    store.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # Create and save a valid checkpoint
    cp = Checkpoint.create(
        checkpoint_type="node_start",
        session_id="test_session",
        run_id="test_run",
        current_node="node_1",
        execution_path=[],
        data_buffer={"a": 1},
    )
    await store.save_checkpoint(cp)

    # Load and verify
    loaded_cp = await store.load_checkpoint(cp.checkpoint_id)
    assert loaded_cp is not None
    assert loaded_cp.checkpoint_id == cp.checkpoint_id
    assert loaded_cp.data_buffer == {"a": 1}


@pytest.mark.asyncio
async def test_load_corrupted_checkpoint_raises_and_isolates(tmp_path):
    # Setup CheckpointStore
    store = CheckpointStore(base_path=tmp_path)
    store.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # Write a corrupted checkpoint file (invalid JSON)
    checkpoint_id = "cp_node_start_node_1_12345"
    checkpoint_path = store.checkpoints_dir / f"{checkpoint_id}.json"
    checkpoint_path.write_text('{"checkpoint_id": "cp_1", "state":', encoding="utf-8")

    # Attempt to load and verify it raises exception
    with pytest.raises(CheckpointCorruptionError) as exc_info:
        await store.load_checkpoint(checkpoint_id)

    assert "is corrupted" in str(exc_info.value)

    # Verify original file is moved to .corrupted
    assert not checkpoint_path.exists()

    corrupted_dir = store.checkpoints_dir / ".corrupted"
    assert corrupted_dir.exists()
    corrupted_files = list(corrupted_dir.glob(f"{checkpoint_id}_*.json"))
    assert len(corrupted_files) == 1
    assert "state" in corrupted_files[0].read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_load_valid_index(tmp_path):
    # Setup CheckpointStore
    store = CheckpointStore(base_path=tmp_path)
    store.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # Create and save a valid checkpoint (which updates index)
    cp = Checkpoint.create(
        checkpoint_type="node_start",
        session_id="test_session",
        run_id="test_run",
        current_node="node_1",
        execution_path=[],
        data_buffer={"a": 1},
    )
    await store.save_checkpoint(cp)

    # Load and verify index
    index = await store.load_index()
    assert index is not None
    assert index.session_id == "test_session"
    assert index.latest_checkpoint_id == cp.checkpoint_id


@pytest.mark.asyncio
async def test_load_corrupted_index_raises_and_isolates(tmp_path):
    # Setup CheckpointStore
    store = CheckpointStore(base_path=tmp_path)
    store.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    # Write a corrupted index file
    store.index_path.write_text('{"session_id": "test_session", "checkpoints":', encoding="utf-8")

    # Attempt to load index and verify it raises exception
    with pytest.raises(CheckpointCorruptionError) as exc_info:
        await store.load_index()

    assert "is corrupted" in str(exc_info.value)

    # Verify original index file is moved to .corrupted
    assert not store.index_path.exists()

    corrupted_dir = store.checkpoints_dir / ".corrupted"
    assert corrupted_dir.exists()
    corrupted_files = list(corrupted_dir.glob("index_*.json"))
    assert len(corrupted_files) == 1
    assert "checkpoints" in corrupted_files[0].read_text(encoding="utf-8")
