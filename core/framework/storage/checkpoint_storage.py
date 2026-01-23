"""
Checkpoint Storage - Filesystem-based persistence for checkpoints.

Stores checkpoints as JSON files organized by run_id.
Designed for easy extension to database storage later.

Directory structure:
    ~/.aden/checkpoints/
    └── {run_id}/
        ├── metadata.json
        ├── checkpoint_001_{node_id}.json
        ├── checkpoint_002_{node_id}.json
        └── ...
"""

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from framework.schemas.checkpoint import Checkpoint, CheckpointMetadata, CheckpointStatus

logger = logging.getLogger(__name__)


class CheckpointStorage:
    """
    Filesystem-based checkpoint storage.
    
    Usage:
        storage = CheckpointStorage()  # Uses default ~/.aden/checkpoints
        
        # Save a checkpoint
        storage.save_checkpoint(checkpoint)
        
        # Load latest checkpoint for recovery
        checkpoint = storage.load_latest_checkpoint(run_id)
        
        # Cleanup after successful completion
        storage.cleanup_run(run_id)
    """
    
    def __init__(self, base_path: Path | str | None = None):
        """
        Initialize checkpoint storage.
        
        Args:
            base_path: Base directory for checkpoints. 
                       Defaults to ~/.aden/checkpoints
        """
        if base_path is None:
            base_path = Path.home() / ".aden" / "checkpoints"
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Checkpoint storage initialized at: {self.base_path}")
    
    def _run_path(self, run_id: str) -> Path:
        """Get the directory path for a run's checkpoints."""
        path = self.base_path / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def _checkpoint_filename(self, checkpoint: Checkpoint) -> str:
        """Generate filename for a checkpoint."""
        safe_node_id = checkpoint.completed_node_id.replace("/", "_").replace("\\", "_")
        return f"checkpoint_{checkpoint.step_number:03d}_{safe_node_id}.json"
    
    def save_checkpoint(self, checkpoint: Checkpoint) -> str:
        """
        Save a checkpoint to disk.
        
        Returns:
            Filepath where checkpoint was saved
        """
        run_path = self._run_path(checkpoint.run_id)
        
        filename = self._checkpoint_filename(checkpoint)
        filepath = run_path / filename
        
        data = checkpoint.model_dump(mode='json')
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        
        logger.debug(f"💾 Saved checkpoint: {filepath}")
        
        self._update_metadata(checkpoint)
        
        return str(filepath)
    
    def load_checkpoint(self, filepath: Path | str) -> Optional[Checkpoint]:
        """Load a checkpoint from a specific file."""
        filepath = Path(filepath)
        if not filepath.exists():
            return None
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            return Checkpoint(**data)
        except Exception as e:
            logger.error(f"Failed to load checkpoint from {filepath}: {e}")
            return None
    
    def load_latest_checkpoint(self, run_id: str) -> Optional[Checkpoint]:
        """
        Load the most recent checkpoint for a run.
        
        Returns:
            The latest Checkpoint, or None if no checkpoints exist
        """
        run_path = self._run_path(run_id)
        
        checkpoint_files = sorted(run_path.glob("checkpoint_*.json"))
        
        if not checkpoint_files:
            logger.debug(f"No checkpoints found for run: {run_id}")
            return None
        
        latest_file = checkpoint_files[-1]
        return self.load_checkpoint(latest_file)
    
    def get_metadata(self, run_id: str) -> Optional[CheckpointMetadata]:
        """Get checkpoint metadata for a run."""
        run_path = self._run_path(run_id)
        meta_path = run_path / "metadata.json"
        
        if not meta_path.exists():
            return None
        
        try:
            with open(meta_path, 'r') as f:
                data = json.load(f)
            return CheckpointMetadata(**data)
        except Exception as e:
            logger.error(f"Failed to load metadata for {run_id}: {e}")
            return None
    
    def _update_metadata(self, checkpoint: Checkpoint) -> None:
        """Update the metadata file after saving a checkpoint."""
        run_path = self._run_path(checkpoint.run_id)
        meta_path = run_path / "metadata.json"
        
        now = datetime.now()
        
        if meta_path.exists():
            try:
                with open(meta_path, 'r') as f:
                    data = json.load(f)
                meta = CheckpointMetadata(**data)
                meta.total_checkpoints += 1
                meta.last_checkpoint_id = checkpoint.id
                meta.last_completed_node = checkpoint.completed_node_id
                meta.last_step_number = checkpoint.step_number
                meta.updated_at = now
            except Exception:
                meta = self._create_metadata(checkpoint, now)
        else:
            meta = self._create_metadata(checkpoint, now)
        
        with open(meta_path, 'w') as f:
            json.dump(meta.model_dump(mode='json'), f, indent=2, default=str)
    
    def _create_metadata(self, checkpoint: Checkpoint, now: datetime) -> CheckpointMetadata:
        """Create new metadata from a checkpoint."""
        return CheckpointMetadata(
            run_id=checkpoint.run_id,
            graph_id=checkpoint.graph_id,
            goal_id=checkpoint.goal_id,
            total_checkpoints=1,
            last_checkpoint_id=checkpoint.id,
            last_completed_node=checkpoint.completed_node_id,
            last_step_number=checkpoint.step_number,
            created_at=now,
            updated_at=now,
            status=CheckpointStatus.IN_PROGRESS,
            original_input=checkpoint.input_data,
        )
    
    def update_status(
        self,
        run_id: str,
        status: CheckpointStatus,
        error_message: str | None = None,
    ) -> None:
        """Update the status of a run's checkpoints."""
        meta = self.get_metadata(run_id)
        if not meta:
            return
        
        meta.status = status
        meta.error_message = error_message
        meta.updated_at = datetime.now()
        
        run_path = self._run_path(run_id)
        meta_path = run_path / "metadata.json"
        
        with open(meta_path, 'w') as f:
            json.dump(meta.model_dump(mode='json'), f, indent=2, default=str)
    
    def cleanup_run(self, run_id: str) -> bool:
        """
        Remove all checkpoints for a run.
        
        Returns:
            True if cleanup succeeded, False otherwise
        """
        run_path = self.base_path / run_id
        
        if not run_path.exists():
            return True
        
        try:
            shutil.rmtree(run_path)
            logger.debug(f"🧹 Cleaned up checkpoints for run: {run_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup checkpoints for {run_id}: {e}")
            return False
