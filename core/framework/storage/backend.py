"""
File-based storage backend for runtime data.

DEPRECATED: This storage backend is deprecated for new sessions.
New sessions use unified storage at sessions/{session_id}/state.json.
This module is kept for backward compatibility with old run data only.

Uses Pydantic's built-in serialization.
"""

import json
from pathlib import Path

from framework.schemas.run import Run, RunStatus, RunSummary
from framework.utils.io import atomic_write


class FileStorage:
    """
    DEPRECATED: File-based storage for old runs only.

    New sessions use unified storage at sessions/{session_id}/state.json.
    This class is kept for backward compatibility with old run data.

    Old directory structure (deprecated):
    {base_path}/
      runs/            # DEPRECATED - no longer written
        {run_id}.json
      summaries/       # DEPRECATED - no longer written
        {run_id}.json
      indexes/         # DEPRECATED - no longer written or read
        by_goal/
          {goal_id}.json
        by_status/
          {status}.json
        by_node/
          {node_id}.json
    """

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist.

        DEPRECATED: All directories (runs/, summaries/, indexes/) are deprecated.
        New sessions use unified storage at sessions/{session_id}/state.json.
        This method is now a no-op. Tests should not rely on this.
        """
        # No-op: do not create deprecated directories
        pass

    def _validate_key(self, key: str) -> None:
        """
        Validate key to prevent path traversal attacks.

        Args:
            key: The key to validate

        Raises:
            ValueError: If key contains path traversal or dangerous patterns
        """
        if not key or key.strip() == "":
            raise ValueError("Key cannot be empty")

        # Block path separators
        if "/" in key or "\\" in key:
            raise ValueError(f"Invalid key format: path separators not allowed in '{key}'")

        # Block parent directory references
        if ".." in key or key.startswith("."):
            raise ValueError(f"Invalid key format: path traversal detected in '{key}'")

        # Block absolute paths
        if key.startswith("/") or (len(key) > 1 and key[1] == ":"):
            raise ValueError(f"Invalid key format: absolute paths not allowed in '{key}'")

        # Block null bytes (Unix path injection)
        if "\x00" in key:
            raise ValueError("Invalid key format: null bytes not allowed")

        # Block other dangerous special characters
        dangerous_chars = {"<", ">", "|", "&", "$", "`", "'", '"'}
        if any(char in key for char in dangerous_chars):
            raise ValueError(f"Invalid key format: contains dangerous characters in '{key}'")

    # === RUN OPERATIONS ===

    def save_run(self, run: Run) -> None:
        """Save a run to storage.

        DEPRECATED: This method is now a no-op.
        New sessions use unified storage at sessions/{session_id}/state.json.
        Tests should not rely on FileStorage - use unified session storage instead.
        """
        import warnings

        warnings.warn(
            "FileStorage.save_run() is deprecated. "
            "New sessions use unified storage at sessions/{session_id}/state.json. "
            "This write has been skipped.",
            DeprecationWarning,
            stacklevel=2,
        )
        # No-op: do not write to deprecated locations

    def load_run(self, run_id: str) -> Run | None:
        """Load a run from storage."""
        run_path = self.base_path / "runs" / f"{run_id}.json"
        if not run_path.exists():
            return None
        with open(run_path, encoding="utf-8") as f:
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

        with open(summary_path, encoding="utf-8") as f:
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
        """Get all run IDs for a goal.

        DEPRECATED: Indexes are deprecated. For new sessions, scan sessions/*/state.json instead.
        This method only returns old run IDs from deprecated indexes.
        """
        import warnings

        warnings.warn(
            "FileStorage.get_runs_by_goal() is deprecated. "
            "For new sessions, scan sessions/*/state.json instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._get_index("by_goal", goal_id)

    def get_runs_by_status(self, status: str | RunStatus) -> list[str]:
        """Get all run IDs with a status.

        DEPRECATED: Indexes are deprecated. For new sessions, scan sessions/*/state.json instead.
        This method only returns old run IDs from deprecated indexes.
        """
        import warnings

        warnings.warn(
            "FileStorage.get_runs_by_status() is deprecated. "
            "For new sessions, scan sessions/*/state.json instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        if isinstance(status, RunStatus):
            status = status.value
        return self._get_index("by_status", status)

    def get_runs_by_node(self, node_id: str) -> list[str]:
        """Get all run IDs that executed a node.

        DEPRECATED: Indexes are deprecated. For new sessions, scan sessions/*/state.json instead.
        This method only returns old run IDs from deprecated indexes.
        """
        import warnings

        warnings.warn(
            "FileStorage.get_runs_by_node() is deprecated. "
            "For new sessions, scan sessions/*/state.json instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._get_index("by_node", node_id)

    def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        runs_dir = self.base_path / "runs"
        return [f.stem for f in runs_dir.glob("*.json")]

    def list_all_goals(self) -> list[str]:
        """List all goal IDs that have runs.

        DEPRECATED: Indexes are deprecated. For new sessions, scan sessions/*/state.json instead.
        This method only returns goals from old run IDs in deprecated indexes.
        """
        import warnings

        warnings.warn(
            "FileStorage.list_all_goals() is deprecated. "
            "For new sessions, scan sessions/*/state.json instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        goals_dir = self.base_path / "indexes" / "by_goal"
        if not goals_dir.exists():
            return []
        return [f.stem for f in goals_dir.glob("*.json")]

    # === INDEX OPERATIONS ===

    def _get_index(self, index_type: str, key: str) -> list[str]:
        """Get values from an index."""
        self._validate_key(key)  # Prevent path traversal
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        if not index_path.exists():
            return []
        with open(index_path, encoding="utf-8") as f:
            return json.load(f)

    def _add_to_index(self, index_type: str, key: str, value: str) -> None:
        """Add a value to an index."""
        self._validate_key(key)  # Prevent path traversal
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        values = self._get_index(index_type, key)  # Already validated in _get_index
        if value not in values:
            values.append(value)
            with atomic_write(index_path) as f:
                json.dump(values, f, indent=2)

    def _remove_from_index(self, index_type: str, key: str, value: str) -> None:
        """Remove a value from an index."""
        self._validate_key(key)  # Prevent path traversal
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        values = self._get_index(index_type, key)  # Already validated in _get_index
        if value in values:
            values.remove(value)
            with atomic_write(index_path) as f:
                json.dump(values, f, indent=2)

    # === UTILITY ===

    def get_stats(self) -> dict:
        """Get storage statistics."""
        return {
            "total_runs": len(self.list_all_runs()),
            "total_goals": len(self.list_all_goals()),
            "storage_path": str(self.base_path),
        }
