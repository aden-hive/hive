"""
File-based storage backend for runtime data.

Stores runs as JSON files with indexes for efficient querying.
Uses Pydantic's built-in serialization.
"""

import json
import threading
from pathlib import Path
from contextlib import contextmanager

from framework.schemas.run import Run, RunSummary, RunStatus

# Platform-specific file locking
import sys
if sys.platform == "win32":
    import msvcrt
    def lock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
    def unlock_file(f):
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl
    def lock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
    def unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


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
        # Thread locks for in-process synchronization
        self._locks = {}
        self._locks_lock = threading.Lock()

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

    def _get_lock(self, key: str) -> threading.Lock:
        """Get or create a lock for a specific file."""
        with self._locks_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]

    @contextmanager
    def _file_lock(self, path: Path):
        """Context manager for OS-level file locking."""
        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Open in r+ mode if exists, w+ if not
        mode = "r+" if path.exists() else "w+"
        f = open(path, mode)
        try:
            lock_file(f)
            yield f
        finally:
            unlock_file(f)
            f.close()

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
        
        # Use thread lock for in-process synchronization
        lock = self._get_lock(f"index:{index_type}:{key}")
        with lock:
            # Use file lock for cross-process synchronization
            with self._file_lock(index_path) as f:
                f.seek(0)
                content = f.read()
                try:
                    return json.loads(content) if content.strip() else []
                except (json.JSONDecodeError, ValueError):
                    return []

    def _add_to_index(self, index_type: str, key: str, value: str) -> None:
        """Add a value to an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        
        # Use thread lock for in-process synchronization
        lock = self._get_lock(f"index:{index_type}:{key}")
        with lock:
            # Use file lock for cross-process synchronization
            with self._file_lock(index_path) as f:
                # Read current values
                try:
                    f.seek(0)
                    content = f.read()
                    values = json.loads(content) if content.strip() else []
                except (json.JSONDecodeError, ValueError):
                    values = []
                
                # Add value if not present
                if value not in values:
                    values.append(value)
                    
                    # Write back atomically
                    f.seek(0)
                    f.truncate()
                    json.dump(values, f)
                    f.flush()

    def _remove_from_index(self, index_type: str, key: str, value: str) -> None:
        """Remove a value from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        
        if not index_path.exists():
            return
        
        # Use thread lock for in-process synchronization
        lock = self._get_lock(f"index:{index_type}:{key}")
        with lock:
            # Use file lock for cross-process synchronization
            with self._file_lock(index_path) as f:
                # Read current values
                try:
                    f.seek(0)
                    content = f.read()
                    values = json.loads(content) if content.strip() else []
                except (json.JSONDecodeError, ValueError):
                    values = []
                
                # Remove value if present
                if value in values:
                    values.remove(value)
                    
                    # Write back atomically
                    f.seek(0)
                    f.truncate()
                    json.dump(values, f)
                    f.flush()

    # === UTILITY ===

    def get_stats(self) -> dict:
        """Get storage statistics."""
        return {
            "total_runs": len(self.list_all_runs()),
            "total_goals": len(self.list_all_goals()),
            "storage_path": str(self.base_path),
        }
