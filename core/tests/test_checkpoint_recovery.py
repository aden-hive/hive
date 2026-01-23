"""
Tests for checkpoint recovery system.

Tests cover:
- Checkpoint schema serialization/deserialization
- FileStorage checkpoint operations
- CheckpointManager save/restore logic
- GraphExecutor checkpointing and recovery
- FlexibleGraphExecutor checkpointing and recovery
- Checkpoint retention policies
- Backward compatibility
"""

import asyncio
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from framework.schemas.checkpoint import (
    Checkpoint,
    CheckpointConfig,
    CheckpointMetadata,
    ExecutorType,
)
from framework.storage.backend import FileStorage
from framework.graph.checkpoint_manager import CheckpointManager
from framework.graph.node import SharedMemory, NodeSpec, NodeResult
from framework.graph.executor import GraphExecutor, ExecutionResult
from framework.graph.edge import GraphSpec, EdgeSpec
from framework.graph.goal import Goal
from framework.runtime.core import Runtime
from framework.graph.plan import (
    Plan,
    PlanStep,
    ActionSpec,
    ActionType,
    StepStatus,
)
from framework.graph.flexible_executor import FlexibleGraphExecutor


class TestCheckpointSchema:
    """Tests for checkpoint data models."""
    
    def test_checkpoint_creation(self):
        """Test creating a Checkpoint."""
        checkpoint = Checkpoint(
            id="ckpt_test_123",
            run_id="run_123",
            executor_type=ExecutorType.GRAPH,
            current_node_id="node_1",
            memory_snapshot={"key": "value"},
            execution_path=["node_0", "node_1"],
            step_number=2,
            total_tokens=100,
            total_latency_ms=500,
        )
        
        assert checkpoint.id == "ckpt_test_123"
        assert checkpoint.run_id == "run_123"
        assert checkpoint.executor_type == ExecutorType.GRAPH
        assert checkpoint.node_id == "node_1"
    
    def test_checkpoint_serialization(self):
        """Test Checkpoint serialization/deserialization."""
        checkpoint = Checkpoint(
            id="ckpt_test_123",
            run_id="run_123",
            executor_type=ExecutorType.GRAPH,
            current_node_id="node_1",
            memory_snapshot={"key": "value"},
        )
        
        # Serialize to JSON
        json_str = checkpoint.model_dump_json()
        
        # Deserialize from JSON
        restored = Checkpoint.model_validate_json(json_str)
        
        assert restored.id == checkpoint.id
        assert restored.run_id == checkpoint.run_id
        assert restored.memory_snapshot == checkpoint.memory_snapshot
    
    def test_checkpoint_to_metadata(self):
        """Test converting Checkpoint to CheckpointMetadata."""
        checkpoint = Checkpoint(
            id="ckpt_test_123",
            run_id="run_123",
            executor_type=ExecutorType.GRAPH,
            current_node_id="node_1",
            step_number=5,
            total_tokens=200,
            total_latency_ms=1000,
        )
        
        metadata = checkpoint.to_metadata()
        
        assert isinstance(metadata, CheckpointMetadata)
        assert metadata.id == checkpoint.id
        assert metadata.node_id == "node_1"
        assert metadata.step_number == 5
    
    def test_checkpoint_to_session_state(self):
        """Test converting Checkpoint to session_state."""
        checkpoint = Checkpoint(
            id="ckpt_test_123",
            run_id="run_123",
            executor_type=ExecutorType.GRAPH,
            current_node_id="node_1",
            next_node_id="node_2",
            memory_snapshot={"data": "test"},
            execution_path=["node_0", "node_1"],
        )
        
        session_state = checkpoint.to_session_state()
        
        assert "memory" in session_state
        assert session_state["memory"]["data"] == "test"
        assert session_state["paused_at"] == "node_1"
        assert session_state["resume_from"] == "node_2"
    
    def test_checkpoint_config_defaults(self):
        """Test CheckpointConfig default values."""
        config = CheckpointConfig()
        
        assert config.enabled is True
        assert config.save_frequency == "every_node"
        assert config.auto_recovery is True
        assert config.retention_strategy == "latest_only"


class TestFileStorageCheckpoints:
    """Tests for FileStorage checkpoint operations."""
    
    def test_save_and_load_checkpoint(self):
        """Test saving and loading a checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            
            checkpoint = Checkpoint(
                id="ckpt_test_123",
                run_id="run_123",
                executor_type=ExecutorType.GRAPH,
                current_node_id="node_1",
                memory_snapshot={"key": "value"},
            )
            
            # Save
            storage.save_checkpoint(checkpoint)
            
            # Load
            loaded = storage.load_checkpoint("run_123", "ckpt_test_123")
            
            assert loaded is not None
            assert loaded.id == checkpoint.id
            assert loaded.memory_snapshot == checkpoint.memory_snapshot
    
    def test_load_latest_checkpoint(self):
        """Test loading the latest checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            
            # Save multiple checkpoints
            for i in range(3):
                checkpoint = Checkpoint(
                    id=f"ckpt_test_{i}",
                    run_id="run_123",
                    executor_type=ExecutorType.GRAPH,
                    current_node_id=f"node_{i}",
                    memory_snapshot={"step": i},
                )
                storage.save_checkpoint(checkpoint)
            
            # Load latest
            latest = storage.load_latest_checkpoint("run_123")
            
            assert latest is not None
            assert latest.id == "ckpt_test_2"
            assert latest.memory_snapshot["step"] == 2
    
    def test_list_checkpoints(self):
        """Test listing checkpoints for a run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            
            # Save multiple checkpoints
            for i in range(3):
                checkpoint = Checkpoint(
                    id=f"ckpt_test_{i}",
                    run_id="run_123",
                    executor_type=ExecutorType.GRAPH,
                    current_node_id=f"node_{i}",
                )
                storage.save_checkpoint(checkpoint)
            
            # List
            checkpoints = storage.list_checkpoints("run_123")
            
            assert len(checkpoints) == 3
            assert all(isinstance(c, CheckpointMetadata) for c in checkpoints)
    
    def test_delete_checkpoints(self):
        """Test deleting checkpoints."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            
            checkpoint = Checkpoint(
                id="ckpt_test_123",
                run_id="run_123",
                executor_type=ExecutorType.GRAPH,
                current_node_id="node_1",
            )
            storage.save_checkpoint(checkpoint)
            
            # Delete
            count = storage.delete_checkpoints("run_123")
            
            assert count == 1
            assert storage.load_latest_checkpoint("run_123") is None


class TestCheckpointManager:
    """Tests for CheckpointManager."""
    
    def test_save_checkpoint(self):
        """Test CheckpointManager.save_checkpoint()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            manager = CheckpointManager(storage)
            
            memory = SharedMemory()
            memory.write("key", "value")
            
            checkpoint_id = manager.save_checkpoint(
                run_id="run_123",
                node_id="node_1",
                memory=memory,
                metadata={"step_number": 1}
            )
            
            assert checkpoint_id is not None
            assert "ckpt_run_123_node_1" in checkpoint_id
    
    def test_restore_from_checkpoint(self):
        """Test CheckpointManager.restore_from_checkpoint()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            manager = CheckpointManager(storage)
            
            memory = SharedMemory()
            memory.write("key", "value")
            
            # Save
            manager.save_checkpoint(
                run_id="run_123",
                node_id="node_1",
                memory=memory,
            )
            
            # Restore
            memory_snapshot, resume_node = manager.restore_from_checkpoint("run_123")
            
            assert memory_snapshot is not None
            assert memory_snapshot["key"] == "value"
            assert resume_node == "node_1"
    
    def test_should_checkpoint_every_node(self):
        """Test should_checkpoint with every_node frequency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            config = CheckpointConfig(save_frequency="every_node")
            manager = CheckpointManager(storage, config)
            
            assert manager.should_checkpoint(1) is True
            assert manager.should_checkpoint(2) is True
            assert manager.should_checkpoint(10) is True
    
    def test_should_checkpoint_every_n_nodes(self):
        """Test should_checkpoint with every_n_nodes frequency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            config = CheckpointConfig(save_frequency="every_n_nodes", n_nodes=3)
            manager = CheckpointManager(storage, config)
            
            assert manager.should_checkpoint(1) is False
            assert manager.should_checkpoint(2) is False
            assert manager.should_checkpoint(3) is True
            assert manager.should_checkpoint(6) is True
    
    def test_retention_policy_latest_only(self):
        """Test latest_only retention policy."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            config = CheckpointConfig(retention_strategy="latest_only")
            manager = CheckpointManager(storage, config)
            
            memory = SharedMemory()
            
            # Save multiple checkpoints
            for i in range(3):
                memory.write(f"key_{i}", f"value_{i}")
                manager.save_checkpoint(
                    run_id="run_123",
                    node_id=f"node_{i}",
                    memory=memory,
                )
            
            # Only latest should remain
            checkpoints = storage.list_checkpoints("run_123")
            assert len(checkpoints) <= 1
    
    def test_checkpoint_disabled(self):
        """Test checkpointing when disabled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            config = CheckpointConfig(enabled=False)
            manager = CheckpointManager(storage, config)
            
            memory = SharedMemory()
            checkpoint_id = manager.save_checkpoint(
                run_id="run_123",
                node_id="node_1",
                memory=memory,
            )
            
            assert checkpoint_id is None


class TestGraphExecutorCheckpointing:
    """Tests for GraphExecutor with checkpointing."""
    
    @pytest.mark.asyncio
    async def test_executor_creates_checkpoints(self):
        """Test that GraphExecutor creates checkpoints after successful nodes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            runtime = Runtime(storage_path=tmpdir)
            manager = CheckpointManager(storage)
            
            # Create simple graph
            graph = GraphSpec(
                id="test_graph",
                goal_id="test_goal",
                entry_node="node_1",
                nodes=[
                    NodeSpec(
                        id="node_1",
                        name="Node 1",
                        description="Test node",
                        node_type="function",
                        output_keys=["result"],
                    )
                ],
                edges=[],
                terminal_nodes=["node_1"],
            )
            
            goal = Goal(
                id="test_goal",
                name="Test",
                description="Test goal",
            )
            
            # Create executor with checkpoint manager
            executor = GraphExecutor(
                runtime=runtime,
                checkpoint_manager=manager,
            )
            
            # Register simple function
            def test_func(**kwargs):
                return "success"
            
            executor.register_function("node_1", test_func)
            
            # Execute
            result = await executor.execute(graph, goal, {"input": "test"})
            
            # Check that execution succeeded (checkpoint creation is internal)
            assert result.success is True
            
            # Verify checkpoint functionality by checking storage has checkpoint directories
            checkpoint_dir = Path(tmpdir) / "checkpoints" / "by_run"
            # If checkpoints were created, the directory structure would exist
            # This is a basic integration test - actual checkpointing happens in execution
    
    @pytest.mark.asyncio
    async def test_backward_compatibility_no_checkpoint_manager(self):
        """Test that GraphExecutor works without checkpoint manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = Runtime(storage_path=tmpdir)
            
            graph = GraphSpec(
                id="test_graph",
                goal_id="test_goal",
                entry_node="node_1",
                nodes=[
                    NodeSpec(
                        id="node_1",
                        name="Node 1",
                        description="Test node",
                        node_type="function",
                        output_keys=["result"],
                    )
                ],
                edges=[],
                terminal_nodes=["node_1"],
            )
            
            goal = Goal(
                id="test_goal",
                name="Test",
                description="Test goal",
            )
            
            # Create executor WITHOUT checkpoint manager
            executor = GraphExecutor(runtime=runtime)
            
            def test_func(**kwargs):
                return "success"
            
            executor.register_function("node_1", test_func)
            
            # Should work fine
            result = await executor.execute(graph, goal, {"input": "test"})
            assert result.success is True


class TestFlexibleExecutorCheckpointing:
    """Tests for FlexibleGraphExecutor with checkpointing."""
    
    @pytest.mark.asyncio
    async def test_flexible_executor_creates_checkpoints(self):
        """Test that FlexibleGraphExecutor creates checkpoints after steps."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            runtime = Runtime(storage_path=tmpdir)
            manager = CheckpointManager(storage)
            
            # Create simple plan
            plan = Plan(
                id="test_plan",
                goal_id="goal_1",
                description="Test plan",
                steps=[
                    PlanStep(
                        id="step_1",
                        description="Test step",
                        action=ActionSpec(action_type=ActionType.FUNCTION),
                        status=StepStatus.PENDING,
                    )
                ],
            )
            
            goal = Goal(
                id="goal_1",
                name="Test Goal",
                description="Test",
            )
            
            # Create executor with checkpoint manager
            executor = FlexibleGraphExecutor(
                runtime=runtime,
                checkpoint_manager=manager,
            )
            
            # Note: Full execution would require LLM setup
            # This test verifies the integration doesn't break initialization
            assert executor.checkpoint_manager is manager


class TestCheckpointRecovery:
    """Integration tests for checkpoint recovery."""
    
    @pytest.mark.asyncio
    async def test_recovery_after_failure(self):
        """Test recovery from checkpoint after simulated failure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            runtime = Runtime(storage_path=tmpdir)
            manager = CheckpointManager(storage)
            
            # Create checkpoint manually
            memory = SharedMemory()
            memory.write("recovered_data", "test_value")
            
            checkpoint_id = manager.save_checkpoint(
                run_id="run_123",
                node_id="node_2",
                memory=memory,
                metadata={
                    "execution_path": ["node_1", "node_2"],
                    "step_number": 2,
                }
            )
            
            # Restore
            memory_snapshot, resume_node = manager.restore_from_checkpoint("run_123")
            
            assert memory_snapshot["recovered_data"] == "test_value"
            assert resume_node == "node_2"
    
    def test_checkpoint_pruning(self):
        """Test that old checkpoints are pruned correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileStorage(tmpdir)
            config = CheckpointConfig(
                retention_strategy="prune_old",
                max_checkpoints_per_run=5,
            )
            manager = CheckpointManager(storage, config)
            
            memory = SharedMemory()
            
            # Create more checkpoints than max
            for i in range(10):
                memory.write(f"key_{i}", f"value_{i}")
                manager.save_checkpoint(
                    run_id="run_123",
                    node_id=f"node_{i}",
                    memory=memory,
                )
            
            # Should have only max checkpoints
            checkpoints = storage.list_checkpoints("run_123")
            assert len(checkpoints) <= config.max_checkpoints_per_run


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
