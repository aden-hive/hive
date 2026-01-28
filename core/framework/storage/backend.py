"""
File-based storage backend for runtime data.

Stores runs as JSON files with indexes for efficient querying.
Uses Pydantic's built-in serialization.
"""

import json
from pathlib import Path

from framework.schemas.run import Run, RunStatus, RunSummary


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
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # === ATOMICITY HELPERS ===

    def _atomic_write(self, path: Path, data: str) -> None:
        """
        Write data atomically to a file.
        
        Writes to a temp file first, then renames it to the target path.
        This prevents partially written files from being read.
        """
        import os
        import tempfile
        
        # Create temp file in same directory to ensure atomic rename
        dir_path = path.parent
        dir_path.mkdir(parents=True, exist_ok=True)
        
        fd, temp_path = tempfile.mkstemp(dir=dir_path, text=True)
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())  # Ensure data is on disk
                
            # Atomic rename
            os.replace(temp_path, path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(temp_path)
            except OSError:
                pass
            raise

    def _lock_file(self, path: Path):
        """
        Context manager for file locking.
        
        Uses a simple .lock file strategy. 
        Wait loop with timeout to acquire lock.
        """
        import time
        import contextlib
        
        lock_path = path.with_suffix(path.suffix + ".lock")
        
        @contextlib.contextmanager
        def lock_context():
            timeout = 10.0
            start_time = time.time()
            acquired = False
            
            try:
                while time.time() - start_time < timeout:
                    try:
                        # Exclusive creation fails if file exists
                        with open(lock_path, "x"):
                            acquired = True
                            break
                    except FileExistsError:
                        time.sleep(0.05)
                        
                if not acquired:
                    raise TimeoutError(f"Could not acquire lock for {path} after {timeout}s")
                
                yield
                
            finally:
                if acquired:
                    try:
                        lock_path.unlink()
                    except OSError:
                        pass
                        
        return lock_context()

    # === RUN OPERATIONS ===

    def save_run(self, run: Run) -> None:
        """Save a run to storage."""
        # Save full run using Pydantic's model_dump_json
        run_path = self.base_path / "runs" / f"{run.id}.json"
        self._atomic_write(run_path, run.model_dump_json(indent=2))

        # Save summary
        summary = RunSummary.from_run(run)
        summary_path = self.base_path / "summaries" / f"{run.id}.json"
        self._atomic_write(summary_path, summary.model_dump_json(indent=2))

        # Update indexes (with locking for each index file)
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
        
        # Use simple retry for reading (imperfect but better than nothing)
        import time
        for _ in range(3):
            try:
                with open(index_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                time.sleep(0.01)
                
        # If failed after retries, try one last time without catch
        try:
            with open(index_path) as f:
                return json.load(f)
        except FileNotFoundError:
            return []

    def _add_to_index(self, index_type: str, key: str, value: str) -> None:
        """Add a value to an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        
        # Ensure parent dir exists
        index_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Lock before read-modify-write cycle
        with self._lock_file(index_path):
            values = []
            if index_path.exists():
                try:
                    with open(index_path) as f:
                        values = json.load(f)
                except json.JSONDecodeError:
                    pass # Overwrite corrupt file
            
            if value not in values:
                values.append(value)
                self._atomic_write(index_path, json.dumps(values))

    def _remove_from_index(self, index_type: str, key: str, value: str) -> None:
        """Remove a value from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        
        if not index_path.exists():
            return
            
        with self._lock_file(index_path):
            try:
                with open(index_path) as f:
                    values = json.load(f)
            except json.JSONDecodeError:
                return
                
            if value in values:
                values.remove(value)
                self._atomic_write(index_path, json.dumps(values))

    # === UTILITY ===

    def get_stats(self) -> dict:
        """Get storage statistics."""
        return {
            "total_runs": len(self.list_all_runs()),
            "total_goals": len(self.list_all_goals()),
            "storage_path": str(self.base_path),
        }
