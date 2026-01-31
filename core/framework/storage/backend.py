"""
File-based storage backend for runtime data.

Stores runs as JSON files with indexes for efficient querying.
Uses Pydantic's built-in serialization.
"""

import json
from pathlib import Path

from framework.schemas.run import Run, RunStatus, RunSummary
from framework.utils.io import atomic_write


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

    def __init__(
        self,
        base_path: str | Path,
        self_healing: bool = False,
        integrity_check_on_init: bool = False,
    ):
        self.base_path = Path(base_path)
        self.self_healing = self_healing
        self._ensure_dirs()

        if integrity_check_on_init:
            self.reconcile_indexes()

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
        """Save a run to storage."""
        # Save full run using Pydantic's model_dump_json
        run_path = self.base_path / "runs" / f"{run.id}.json"
        with atomic_write(run_path) as f:
            f.write(run.model_dump_json(indent=2))

        # Save summary
        summary = RunSummary.from_run(run)
        summary_path = self.base_path / "summaries" / f"{run.id}.json"
        with atomic_write(summary_path) as f:
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

    def get_runs_by_goal(self, goal_id: str, validate: bool = False) -> list[str]:
        """Get all run IDs for a goal."""
        return self._get_index("by_goal", goal_id, validate=validate)

    def get_runs_by_status(
        self, status: str | RunStatus, validate: bool = False
    ) -> list[str]:
        """Get all run IDs with a status."""
        if isinstance(status, RunStatus):
            status = status.value
        return self._get_index("by_status", status, validate=validate)

    def get_runs_by_node(self, node_id: str, validate: bool = False) -> list[str]:
        """Get all run IDs that executed a node."""
        return self._get_index("by_node", node_id, validate=validate)

    def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        runs_dir = self.base_path / "runs"
        return [f.stem for f in runs_dir.glob("*.json")]

    def list_all_goals(self) -> list[str]:
        """List all goal IDs that have runs."""
        goals_dir = self.base_path / "indexes" / "by_goal"
        return [f.stem for f in goals_dir.glob("*.json")]

    # === INDEX OPERATIONS ===

    def _get_index(
        self, index_type: str, key: str, validate: bool = False
    ) -> list[str]:
        """Get values from an index."""
        self._validate_key(key)  # Prevent path traversal
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        if not index_path.exists():
            return []
        with open(index_path, encoding="utf-8") as f:
            values = json.load(f)

        # Validate against actual run files if requested or if self-healing is on
        if validate or self.self_healing:
            str_values = [str(v) for v in values]
            valid_values = []
            needs_update = False

            runs_dir = self.base_path / "runs"
            for value in str_values:
                # Check if run file exists
                if (runs_dir / f"{value}.json").exists():
                    valid_values.append(value)
                else:
                    needs_update = True

            if needs_update and self.self_healing:
                # Self-heal: update the index file immediately
                with atomic_write(index_path) as f:
                    json.dump(valid_values, f, indent=2)
                return valid_values
            elif needs_update and validate:
                # Just return valid values without updating file
                return valid_values
            
        return values

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

    def reconcile_indexes(self, dry_run: bool = False) -> dict[str, list[str]]:
        """
        Reconcile indexes against actual run files on disk.

        Removes any run IDs from indexes that don't have corresponding
        run files, ensuring query APIs return only valid IDs.

        Args:
            dry_run: If True, only report inconsistencies without modifying.

        Returns:
            Dict mapping index type to list of removed invalid run IDs.
        """
        # Get authoritative set of existing run IDs
        runs_dir = self.base_path / "runs"
        valid_run_ids = {f.stem for f in runs_dir.glob("*.json")}
        
        removed: dict[str, list[str]] = {"by_goal": [], "by_status": [], "by_node": []}

        for index_type in ("by_goal", "by_status", "by_node"):
            index_dir = self.base_path / "indexes" / index_type
            if not index_dir.exists():
                continue
                
            for index_file in index_dir.glob("*.json"):
                key = index_file.stem
                
                # Use base load logic to avoid recursion/validation loop
                with open(index_file, encoding="utf-8") as f:
                    current_ids = json.load(f)
                
                invalid_ids = [rid for rid in current_ids if rid not in valid_run_ids]

                if invalid_ids:
                    removed[index_type].extend(invalid_ids)
                    if not dry_run:
                        valid_ids = [rid for rid in current_ids if rid in valid_run_ids]
                        # If index becomes empty, we could delete it, but keeping empty list is also fine
                        with atomic_write(index_file) as f:
                            json.dump(valid_ids, f, indent=2)

        return removed

    def rebuild_indexes(self) -> None:
        """
        Rebuild all indexes from scratch using run files as source of truth.

        Clears existing indexes and re-populates from actual run data.
        Use when indexes are severely corrupted or after bulk operations.
        """
        # Clear all existing indexes
        for index_type in ("by_goal", "by_status", "by_node"):
            index_dir = self.base_path / "indexes" / index_type
            if index_dir.exists():
                for index_file in index_dir.glob("*.json"):
                    index_file.unlink()

        # Rebuild from run files
        for run_id in self.list_all_runs():
            run = self.load_run(run_id)
            if run:
                self._add_to_index("by_goal", run.goal_id, run.id)
                self._add_to_index("by_status", run.status.value, run.id)
                for node_id in run.metrics.nodes_executed:
                    self._add_to_index("by_node", node_id, run.id)
