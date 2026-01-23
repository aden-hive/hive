"""
Unit tests for Checkpoint System.

These tests verify the checkpoint functionality WITHOUT requiring any API key.
All tests use pure Python - no LLM calls needed.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime

from framework.schemas.checkpoint import (
    Checkpoint,
    CheckpointMetadata,
    CheckpointStatus,
)
from framework.storage.checkpoint_storage import CheckpointStorage
from framework.runtime.checkpoint import CheckpointManager


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def temp_storage_path():
    """Create a temporary directory for checkpoint storage."""
    path = Path(tempfile.mkdtemp(prefix="checkpoint_test_"))
    yield path
    # Cleanup after test
    if path.exists():
        shutil.rmtree(path)


@pytest.fixture
def checkpoint_storage(temp_storage_path):
    """Create a CheckpointStorage instance with temp path."""
    return CheckpointStorage(temp_storage_path)


@pytest.fixture
def checkpoint_manager(temp_storage_path):
    """Create a CheckpointManager instance with temp path."""
    return CheckpointManager(
        storage_path=temp_storage_path,
        enabled=True,
        auto_cleanup=False,  # Keep checkpoints for testing
    )


@pytest.fixture
def sample_checkpoint():
    """Create a sample checkpoint for testing."""
    return Checkpoint(
        id="checkpoint_001",
        run_id="test_run_123",
        graph_id="test-graph",
        step_number=1,
        completed_node_id="analyze-request",
        next_node_id="search-web",
        path=["analyze-request"],
        memory_state={
            "topic": "artificial intelligence",
            "analysis": "AI is a broad field...",
            "key_areas": ["machine learning", "neural networks"],
        },
        total_tokens=150,
        total_latency_ms=1200,
        input_data={"topic": "artificial intelligence"},
        goal_id="research-goal",
    )


@pytest.fixture
def sample_checkpoints():
    """Create multiple checkpoints simulating an execution."""
    return [
        Checkpoint(
            id="checkpoint_001",
            run_id="test_run_456",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id="node-2",
            path=["node-1"],
            memory_state={"step": 1, "data": "first"},
            total_tokens=100,
            total_latency_ms=500,
        ),
        Checkpoint(
            id="checkpoint_002",
            run_id="test_run_456",
            graph_id="test-graph",
            step_number=2,
            completed_node_id="node-2",
            next_node_id="node-3",
            path=["node-1", "node-2"],
            memory_state={"step": 2, "data": "second"},
            total_tokens=200,
            total_latency_ms=1000,
        ),
        Checkpoint(
            id="checkpoint_003",
            run_id="test_run_456",
            graph_id="test-graph",
            step_number=3,
            completed_node_id="node-3",
            next_node_id="node-4",
            path=["node-1", "node-2", "node-3"],
            memory_state={"step": 3, "data": "third"},
            total_tokens=300,
            total_latency_ms=1500,
        ),
    ]


# ============================================================================
# CHECKPOINT SCHEMA TESTS
# ============================================================================

class TestCheckpointSchema:
    """Test Checkpoint Pydantic model."""

    def test_checkpoint_creation(self, sample_checkpoint):
        """Test creating a checkpoint with all fields."""
        assert sample_checkpoint.id == "checkpoint_001"
        assert sample_checkpoint.run_id == "test_run_123"
        assert sample_checkpoint.step_number == 1
        assert sample_checkpoint.completed_node_id == "analyze-request"
        assert sample_checkpoint.next_node_id == "search-web"
        assert len(sample_checkpoint.path) == 1
        assert sample_checkpoint.memory_state["topic"] == "artificial intelligence"

    def test_checkpoint_serialization(self, sample_checkpoint):
        """Test checkpoint can be serialized to JSON."""
        data = sample_checkpoint.model_dump(mode='json')
        
        assert isinstance(data, dict)
        assert data["id"] == "checkpoint_001"
        assert data["memory_state"]["topic"] == "artificial intelligence"
        assert isinstance(data["created_at"], str)

    def test_checkpoint_deserialization(self, sample_checkpoint):
        """Test checkpoint can be deserialized from JSON."""
        data = sample_checkpoint.model_dump(mode='json')
        restored = Checkpoint(**data)
        
        assert restored.id == sample_checkpoint.id
        assert restored.memory_state == sample_checkpoint.memory_state
        assert restored.path == sample_checkpoint.path

    def test_checkpoint_defaults(self):
        """Test checkpoint with minimal fields uses correct defaults."""
        checkpoint = Checkpoint(
            id="test",
            run_id="run",
            graph_id="graph",
            step_number=1,
            completed_node_id="node",
        )
        
        assert checkpoint.next_node_id is None
        assert checkpoint.path == []
        assert checkpoint.memory_state == {}
        assert checkpoint.total_tokens == 0
        assert checkpoint.node_result_success is True


class TestCheckpointMetadataSchema:
    """Test CheckpointMetadata Pydantic model."""

    def test_metadata_creation(self):
        """Test creating metadata."""
        meta = CheckpointMetadata(
            run_id="test_run",
            graph_id="test_graph",
            total_checkpoints=3,
            last_checkpoint_id="checkpoint_003",
            last_completed_node="node-3",
        )
        
        assert meta.run_id == "test_run"
        assert meta.total_checkpoints == 3
        assert meta.status == CheckpointStatus.IN_PROGRESS

    def test_metadata_status_values(self):
        """Test all status values."""
        assert CheckpointStatus.IN_PROGRESS == "in_progress"
        assert CheckpointStatus.COMPLETED == "completed"
        assert CheckpointStatus.FAILED == "failed"


# ============================================================================
# CHECKPOINT STORAGE TESTS
# ============================================================================

class TestCheckpointStorage:
    """Test CheckpointStorage filesystem operations."""

    def test_save_checkpoint(self, checkpoint_storage, sample_checkpoint):
        """Test saving a checkpoint to disk."""
        filepath = checkpoint_storage.save_checkpoint(sample_checkpoint)
        
        assert filepath is not None
        assert Path(filepath).exists()
        assert "checkpoint_001" in filepath

    def test_load_checkpoint(self, checkpoint_storage, sample_checkpoint):
        """Test loading a saved checkpoint."""
        filepath = checkpoint_storage.save_checkpoint(sample_checkpoint)
        loaded = checkpoint_storage.load_checkpoint(filepath)
        
        assert loaded is not None
        assert loaded.id == sample_checkpoint.id
        assert loaded.memory_state == sample_checkpoint.memory_state

    def test_load_latest_checkpoint(self, checkpoint_storage, sample_checkpoints):
        """Test loading the latest checkpoint for a run."""
        # Save all checkpoints
        for cp in sample_checkpoints:
            checkpoint_storage.save_checkpoint(cp)
        
        # Load latest
        latest = checkpoint_storage.load_latest_checkpoint("test_run_456")
        
        assert latest is not None
        assert latest.step_number == 3
        assert latest.completed_node_id == "node-3"

    def test_get_metadata(self, checkpoint_storage, sample_checkpoints):
        """Test getting metadata for a run."""
        for cp in sample_checkpoints:
            checkpoint_storage.save_checkpoint(cp)
        
        meta = checkpoint_storage.get_metadata("test_run_456")
        
        assert meta is not None
        assert meta.run_id == "test_run_456"
        assert meta.total_checkpoints == 3
        assert meta.last_step_number == 3

    def test_update_status(self, checkpoint_storage, sample_checkpoint):
        """Test updating checkpoint status."""
        checkpoint_storage.save_checkpoint(sample_checkpoint)
        
        # Update to completed
        checkpoint_storage.update_status(
            sample_checkpoint.run_id,
            CheckpointStatus.COMPLETED,
        )
        
        meta = checkpoint_storage.get_metadata(sample_checkpoint.run_id)
        assert meta.status == CheckpointStatus.COMPLETED

    def test_update_status_with_error(self, checkpoint_storage, sample_checkpoint):
        """Test updating status with error message."""
        checkpoint_storage.save_checkpoint(sample_checkpoint)
        
        checkpoint_storage.update_status(
            sample_checkpoint.run_id,
            CheckpointStatus.FAILED,
            error_message="Node execution failed: timeout",
        )
        
        meta = checkpoint_storage.get_metadata(sample_checkpoint.run_id)
        assert meta.status == CheckpointStatus.FAILED
        assert meta.error_message == "Node execution failed: timeout"

    def test_cleanup_run(self, checkpoint_storage, sample_checkpoints):
        """Test cleaning up checkpoints for a run."""
        for cp in sample_checkpoints:
            checkpoint_storage.save_checkpoint(cp)
        
        # Verify checkpoints exist
        assert checkpoint_storage.load_latest_checkpoint("test_run_456") is not None
        
        # Cleanup
        result = checkpoint_storage.cleanup_run("test_run_456")
        
        assert result is True
        assert checkpoint_storage.load_latest_checkpoint("test_run_456") is None

    def test_load_nonexistent_checkpoint(self, checkpoint_storage):
        """Test loading a checkpoint that doesn't exist."""
        result = checkpoint_storage.load_latest_checkpoint("nonexistent_run")
        assert result is None

    def test_special_characters_in_node_id(self, checkpoint_storage):
        """Test handling special characters in node IDs."""
        checkpoint = Checkpoint(
            id="checkpoint_001",
            run_id="test_run",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node/with/slashes",
        )
        
        filepath = checkpoint_storage.save_checkpoint(checkpoint)
        loaded = checkpoint_storage.load_latest_checkpoint("test_run")
        
        assert loaded is not None
        assert loaded.completed_node_id == "node/with/slashes"


# ============================================================================
# CHECKPOINT MANAGER TESTS
# ============================================================================

class TestCheckpointManager:
    """Test CheckpointManager high-level API."""

    def test_save_checkpoint(self, checkpoint_manager):
        """Test saving a checkpoint via manager."""
        filepath = checkpoint_manager.save(
            run_id="test_run",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id="node-2",
            path=["node-1"],
            memory_state={"key": "value"},
        )
        
        assert filepath is not None

    def test_load_latest(self, checkpoint_manager):
        """Test loading latest checkpoint via manager."""
        # Save some checkpoints
        for i in range(1, 4):
            checkpoint_manager.save(
                run_id="test_run",
                graph_id="test-graph",
                step_number=i,
                completed_node_id=f"node-{i}",
                next_node_id=f"node-{i+1}",
                path=[f"node-{j}" for j in range(1, i+1)],
                memory_state={"step": i},
            )
        
        latest = checkpoint_manager.load_latest("test_run")
        
        assert latest is not None
        assert latest.step_number == 3

    def test_can_resume(self, checkpoint_manager):
        """Test checking if run can be resumed."""
        # No checkpoints yet
        assert checkpoint_manager.can_resume("test_run") is False
        
        # Save a checkpoint
        checkpoint_manager.save(
            run_id="test_run",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id="node-2",
            path=["node-1"],
            memory_state={},
        )
        
        assert checkpoint_manager.can_resume("test_run") is True

    def test_on_execution_complete_success(self, checkpoint_manager):
        """Test completion handler for successful execution."""
        checkpoint_manager.save(
            run_id="test_run",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id=None,
            path=["node-1"],
            memory_state={},
        )
        
        # With auto_cleanup=False, checkpoints should remain but status updated
        checkpoint_manager.on_execution_complete("test_run", success=True)
        
        # Status should be completed (but checkpoints remain since auto_cleanup=False)
        meta = checkpoint_manager.storage.get_metadata("test_run")
        assert meta.status == CheckpointStatus.COMPLETED

    def test_on_execution_complete_failure(self, checkpoint_manager):
        """Test completion handler for failed execution."""
        checkpoint_manager.save(
            run_id="test_run",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id="node-2",
            path=["node-1"],
            memory_state={},
        )
        
        checkpoint_manager.on_execution_complete(
            "test_run",
            success=False,
            error="Connection timeout",
        )
        
        meta = checkpoint_manager.storage.get_metadata("test_run")
        assert meta.status == CheckpointStatus.FAILED
        assert meta.error_message == "Connection timeout"
        
        # Checkpoints should still exist for debugging
        assert checkpoint_manager.can_resume("test_run") is False  # Failed status

    def test_disabled_manager(self, temp_storage_path):
        """Test that disabled manager doesn't save checkpoints."""
        manager = CheckpointManager(
            storage_path=temp_storage_path,
            enabled=False,
        )
        
        result = manager.save(
            run_id="test_run",
            graph_id="test-graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id="node-2",
            path=["node-1"],
            memory_state={},
        )
        
        assert result is None
        assert manager.can_resume("test_run") is False

    def test_cleanup(self, checkpoint_manager):
        """Test manual cleanup."""
        checkpoint_manager.save(
            run_id="test_run",
            graph_id="graph",
            step_number=1,
            completed_node_id="node",
            next_node_id=None,
            path=["node"],
            memory_state={},
        )
        
        result = checkpoint_manager.cleanup("test_run")
        
        assert result is True
        assert checkpoint_manager.load_latest("test_run") is None


# ============================================================================
# INTEGRATION TESTS (Still no API key needed)
# ============================================================================

class TestCheckpointIntegration:
    """Integration tests for checkpoint system."""

    def test_full_save_and_recovery_flow(self, checkpoint_manager):
        """Test complete save and recovery workflow."""
        run_id = "integration_test_run"
        
        # Simulate execution with checkpoints
        memory_states = [
            {"topic": "AI"},
            {"topic": "AI", "analysis": "AI is..."},
            {"topic": "AI", "analysis": "AI is...", "results": ["r1", "r2"]},
        ]
        
        for i, mem in enumerate(memory_states, 1):
            checkpoint_manager.save(
                run_id=run_id,
                graph_id="test-graph",
                step_number=i,
                completed_node_id=f"node-{i}",
                next_node_id=f"node-{i+1}" if i < 3 else None,
                path=[f"node-{j}" for j in range(1, i+1)],
                memory_state=mem,
                total_tokens=i * 100,
                total_latency_ms=i * 500,
            )
        
        # Now recover - check can_resume
        assert checkpoint_manager.can_resume(run_id) is True
        
        # Load checkpoint and verify memory state
        checkpoint = checkpoint_manager.load_latest(run_id)
        
        assert checkpoint.step_number == 3
        assert checkpoint.memory_state["topic"] == "AI"
        assert checkpoint.memory_state["analysis"] == "AI is..."
        assert len(checkpoint.memory_state["results"]) == 2

    def test_multiple_runs_isolation(self, checkpoint_manager):
        """Test that checkpoints for different runs are isolated."""
        # Save checkpoints for run 1
        checkpoint_manager.save(
            run_id="run_1",
            graph_id="graph",
            step_number=1,
            completed_node_id="node-1",
            next_node_id="node-2",
            path=["node-1"],
            memory_state={"run": 1},
        )
        
        # Save checkpoints for run 2
        checkpoint_manager.save(
            run_id="run_2",
            graph_id="graph",
            step_number=1,
            completed_node_id="node-a",
            next_node_id="node-b",
            path=["node-a"],
            memory_state={"run": 2},
        )
        
        # Verify isolation
        cp1 = checkpoint_manager.load_latest("run_1")
        cp2 = checkpoint_manager.load_latest("run_2")
        
        assert cp1.memory_state["run"] == 1
        assert cp2.memory_state["run"] == 2
        assert cp1.completed_node_id == "node-1"
        assert cp2.completed_node_id == "node-a"

    def test_large_memory_state(self, checkpoint_manager):
        """Test handling large memory states."""
        large_data = {
            "results": [{"id": i, "content": f"Result {i}" * 100} for i in range(100)],
            "metadata": {"key": "value" * 1000},
        }
        
        checkpoint_manager.save(
            run_id="large_run",
            graph_id="graph",
            step_number=1,
            completed_node_id="node",
            next_node_id=None,
            path=["node"],
            memory_state=large_data,
        )
        
        loaded = checkpoint_manager.load_latest("large_run")
        
        assert loaded is not None
        assert len(loaded.memory_state["results"]) == 100
        assert loaded.memory_state["results"][50]["id"] == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
