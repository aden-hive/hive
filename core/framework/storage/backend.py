"""
File-based storage backend for runtime data.

Stores runs as JSON files with indexes for efficient querying.
Uses Pydantic's built-in serialization.
"""

import json
from pathlib import Path

from framework.schemas.run import Run, RunSummary, RunStatus
from framework.schemas.checkpoint import Checkpoint, CheckpointMetadata


class FileStorage:
    """
    Simple file-based storage for runs.

    Directory structure:
    {base_path}/
      runs/
        {run_id}.json           # Full run data
      indexes/
        by_goal/
          {goal_id}.json        # List of run IDs for this goal
        by_status/
          {status}.json         # List of run IDs with this status
        by_node/
          {node_id}.json        # List of run IDs that used this node
      summaries/
        {run_id}.json           # Run summary (for quick loading)
    """

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist."""
        dirs = [
            self.base_path / "runs",
            self.base_path / "indexes" / "by_goal",
            self.base_path / "indexes" / "by_status",
            self.base_path / "indexes" / "by_node",
            self.base_path / "summaries",
            self.base_path / "checkpoints" / "by_run",
            self.base_path / "checkpoint_indexes",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # === RUN OPERATIONS ===

    def save_run(self, run: Run) -> None:
        """Save a run to storage."""
        # Save full run using Pydantic's model_dump_json
        run_path = self.base_path / "runs" / f"{run.id}.json"
        with open(run_path, "w") as f:
            f.write(run.model_dump_json(indent=2))

        # Save summary
        summary = RunSummary.from_run(run)
        summary_path = self.base_path / "summaries" / f"{run.id}.json"
        with open(summary_path, "w") as f:
            f.write(summary.model_dump_json(indent=2))

        # Update indexes
        self._add_to_index("by_goal", run.goal_id, run.id)
        self._add_to_index("by_status", run.status.value, run.id)
        for node_id in run.metrics.nodes_executed:
            self._add_to_index("by_node", node_id, run.id)

    def load_run(self, run_id: str) -> Run | None:
        """Load a run from storage."""
        run_path = self.base_path / "runs" / f"{run_id}.json"
        if not run_path.exists():
            return None
        with open(run_path) as f:
            return Run.model_validate_json(f.read())

    def load_summary(self, run_id: str) -> RunSummary | None:
        """Load just the summary (faster than full run)."""
        summary_path = self.base_path / "summaries" / f"{run_id}.json"
        if not summary_path.exists():
            # Fall back to computing from full run
            run = self.load_run(run_id)
            if run:
                return RunSummary.from_run(run)
            return None

        with open(summary_path) as f:
            return RunSummary.model_validate_json(f.read())

    def delete_run(self, run_id: str) -> bool:
        """Delete a run from storage."""
        run_path = self.base_path / "runs" / f"{run_id}.json"
        summary_path = self.base_path / "summaries" / f"{run_id}.json"

        if not run_path.exists():
            return False

        # Load run to get index keys
        run = self.load_run(run_id)
        if run:
            self._remove_from_index("by_goal", run.goal_id, run_id)
            self._remove_from_index("by_status", run.status.value, run_id)
            for node_id in run.metrics.nodes_executed:
                self._remove_from_index("by_node", node_id, run_id)

        run_path.unlink()
        if summary_path.exists():
            summary_path.unlink()

        return True

    # === QUERY OPERATIONS ===

    def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get all run IDs for a goal."""
        return self._get_index("by_goal", goal_id)

    def get_runs_by_status(self, status: str | RunStatus) -> list[str]:
        """Get all run IDs with a status."""
        if isinstance(status, RunStatus):
            status = status.value
        return self._get_index("by_status", status)

    def get_runs_by_node(self, node_id: str) -> list[str]:
        """Get all run IDs that executed a node."""
        return self._get_index("by_node", node_id)

    def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        runs_dir = self.base_path / "runs"
        return [f.stem for f in runs_dir.glob("*.json")]

    def list_all_goals(self) -> list[str]:
        """List all goal IDs that have runs."""
        goals_dir = self.base_path / "indexes" / "by_goal"
        return [f.stem for f in goals_dir.glob("*.json")]

    # === INDEX OPERATIONS ===

    def _get_index(self, index_type: str, key: str) -> list[str]:
        """Get values from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        if not index_path.exists():
            return []
        with open(index_path) as f:
            return json.load(f)

    def _add_to_index(self, index_type: str, key: str, value: str) -> None:
        """Add a value to an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        values = self._get_index(index_type, key)
        if value not in values:
            values.append(value)
            with open(index_path, "w") as f:
                json.dump(values, f)

    def _remove_from_index(self, index_type: str, key: str, value: str) -> None:
        """Remove a value from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        values = self._get_index(index_type, key)
        if value in values:
            values.remove(value)
            with open(index_path, "w") as f:
                json.dump(values, f)

    # === CHECKPOINT OPERATIONS ===

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Save a checkpoint to storage."""
        # Create run-specific directory
        run_dir = self.base_path / "checkpoints" / "by_run" / checkpoint.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        
        # Save checkpoint
        checkpoint_path = run_dir / f"{checkpoint.id}.json"
        with open(checkpoint_path, "w") as f:
            f.write(checkpoint.model_dump_json(indent=2))
        
        # Update latest checkpoint index
        latest_index = self.base_path / "checkpoint_indexes" / f"latest_{checkpoint.run_id}.txt"
        with open(latest_index, "w") as f:
            f.write(checkpoint.id)

    def load_checkpoint(self, run_id: str, checkpoint_id: str) -> Checkpoint | None:
        """Load a specific checkpoint."""
        checkpoint_path = self.base_path / "checkpoints" / "by_run" / run_id / f"{checkpoint_id}.json"
        if not checkpoint_path.exists():
            return None
        with open(checkpoint_path) as f:
            return Checkpoint.model_validate_json(f.read())

    def load_latest_checkpoint(self, run_id: str) -> Checkpoint | None:
        """Load the most recent checkpoint for a run."""
        latest_index = self.base_path / "checkpoint_indexes" / f"latest_{run_id}.txt"
        if not latest_index.exists():
            return None
        
        with open(latest_index) as f:
            checkpoint_id = f.read().strip()
        
        return self.load_checkpoint(run_id, checkpoint_id)

    def list_checkpoints(self, run_id: str) -> list[CheckpointMetadata]:
        """List all checkpoints for a run."""
        run_dir = self.base_path / "checkpoints" / "by_run" / run_id
        if not run_dir.exists():
            return []
        
        checkpoints = []
        for checkpoint_file in sorted(run_dir.glob("*.json")):
            try:
                with open(checkpoint_file) as f:
                    checkpoint = Checkpoint.model_validate_json(f.read())
                    checkpoints.append(checkpoint.to_metadata())
            except Exception:
                continue
        
        # Sort by creation time
        checkpoints.sort(key=lambda c: c.created_at)
        return checkpoints

    def delete_checkpoints(self, run_id: str) -> int:
        """Delete all checkpoints for a run. Returns count of deleted checkpoints."""
        run_dir = self.base_path / "checkpoints" / "by_run" / run_id
        if not run_dir.exists():
            return 0
        
        count = 0
        for checkpoint_file in run_dir.glob("*.json"):
            checkpoint_file.unlink()
            count += 1
        
        # Remove directory if empty
        try:
            run_dir.rmdir()
        except OSError:
            pass
        
        # Remove latest index
        latest_index = self.base_path / "checkpoint_indexes" / f"latest_{run_id}.txt"
        if latest_index.exists():
            latest_index.unlink()
        
        return count

    # === UTILITY ===

    def get_stats(self) -> dict:
        """Get storage statistics."""
        return {
            "total_runs": len(self.list_all_runs()),
            "total_goals": len(self.list_all_goals()),
            "storage_path": str(self.base_path),
        }
