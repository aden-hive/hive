"""
File-based storage backend for failure records.

Follows the same pattern as TestStorage, storing failures as JSON files
with indexes for efficient querying by goal, node, error type, etc.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from collections import Counter
from typing import Any

from framework.testing.failure_record import (
    FailureRecord,
    FailureSeverity,
    FailureSource,
    FailureStats,
)

logger = logging.getLogger(__name__)


class FailureStorage:
    """
    File-based storage for failure records with querying capabilities.
    
    Directory structure:
    {base_path}/
      failures/
        {goal_id}/
          {failure_id}.json        # Full failure data
      indexes/
        by_goal/{goal_id}.json     # List of failure IDs for this goal
        by_node/{node_id}.json     # Failures by node
        by_error_type/{type}.json  # Failures by error type
        by_severity/{level}.json   # Failures by severity
        by_run/{run_id}.json       # Failures by run
      stats/
        {goal_id}_stats.json       # Cached stats for goal
        
    Usage:
        storage = FailureStorage("/path/to/agent/.aden/failures")
        
        # Record a failure
        storage.record_failure(failure)
        
        # Query failures
        failures = storage.get_failures_by_goal("goal_123")
        stats = storage.get_failure_stats("goal_123")
    """
    
    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self._ensure_dirs()
    
    def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist."""
        dirs = [
            self.base_path / "failures",
            self.base_path / "indexes" / "by_goal",
            self.base_path / "indexes" / "by_node",
            self.base_path / "indexes" / "by_error_type",
            self.base_path / "indexes" / "by_severity",
            self.base_path / "indexes" / "by_run",
            self.base_path / "stats",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    
    def _scrub_sensitive_data(self, data: Any) -> Any:
        """
        Recursively scrub sensitive data from dictionaries and lists.
        
        Replaces values for keys containing 'api_key', 'token', or 'password' with '***'.
        """
        if isinstance(data, dict):
            scrubbed = {}
            for key, value in data.items():
                lower_key = key.lower()
                if any(sensitive in lower_key for sensitive in ['api_key', 'token', 'password']):
                    scrubbed[key] = "***"
                else:
                    scrubbed[key] = self._scrub_sensitive_data(value)
            return scrubbed
        elif isinstance(data, list):
            return [self._scrub_sensitive_data(item) for item in data]
        else:
            return data
    
    def _enforce_retention_limit(self) -> None:
        """Enforce retention limit by deleting oldest failures if over 1000 total."""
        failures_dir = self.base_path / "failures"
        all_files = list(failures_dir.glob("**/*.json"))
        
        if len(all_files) <= 1000:
            return
        
        # Sort by modification time (oldest first)
        all_files.sort(key=lambda f: f.stat().st_mtime)
        
        # Delete oldest files
        to_delete = all_files[:len(all_files) - 1000]
        for file_path in to_delete:
            # Parse goal_id and failure_id from path: failures/goal_id/failure_id.json
            parts = file_path.relative_to(failures_dir).parts
            if len(parts) == 2:
                goal_id = parts[0]
                failure_id = file_path.stem  # remove .json
                self.delete_failure(goal_id, failure_id)
    
    # === RECORD OPERATIONS ===
    
    def record_failure(self, failure: FailureRecord) -> str:
        """
        Record a failure and return its ID.
        
        Args:
            failure: The failure record to store
            
        Returns:
            The failure ID
        """
        # Ensure goal directory exists
        goal_dir = self.base_path / "failures" / failure.goal_id
        goal_dir.mkdir(parents=True, exist_ok=True)
        
        # Scrub sensitive data before saving
        failure_data = failure.model_dump()
        scrubbed_data = self._scrub_sensitive_data(failure_data)
        
        # Save full failure record
        failure_path = goal_dir / f"{failure.id}.json"
        with open(failure_path, "w") as f:
            json.dump(scrubbed_data, f, indent=2)
        
        # Retention: Keep only the most recent 1000 failures
        self._enforce_retention_limit()
        
        # Update indexes
        self._add_to_index("by_goal", failure.goal_id, failure.id)
        self._add_to_index("by_severity", failure.severity.value, failure.id)
        self._add_to_index("by_error_type", self._sanitize_key(failure.error_type), failure.id)
        self._add_to_index("by_run", failure.run_id, failure.id)
        
        if failure.node_id:
            self._add_to_index("by_node", failure.node_id, failure.id)
        
        # Invalidate cached stats
        stats_path = self.base_path / "stats" / f"{failure.goal_id}_stats.json"
        if stats_path.exists():
            stats_path.unlink()
        
        logger.debug(f"Recorded failure: {failure.id}")
        return failure.id
    
    def get_failure(self, goal_id: str, failure_id: str) -> FailureRecord | None:
        """Load a specific failure record."""
        failure_path = self.base_path / "failures" / goal_id / f"{failure_id}.json"
        if not failure_path.exists():
            return None
        with open(failure_path) as f:
            return FailureRecord.model_validate_json(f.read())
    
    def delete_failure(self, goal_id: str, failure_id: str) -> bool:
        """Delete a failure record."""
        failure_path = self.base_path / "failures" / goal_id / f"{failure_id}.json"
        
        if not failure_path.exists():
            return False
        
        # Load to get index keys
        failure = self.get_failure(goal_id, failure_id)
        if failure:
            self._remove_from_index("by_goal", failure.goal_id, failure_id)
            self._remove_from_index("by_severity", failure.severity.value, failure_id)
            self._remove_from_index("by_error_type", self._sanitize_key(failure.error_type), failure_id)
            self._remove_from_index("by_run", failure.run_id, failure_id)
            if failure.node_id:
                self._remove_from_index("by_node", failure.node_id, failure_id)
        
        failure_path.unlink()
        return True
    
    # === QUERY OPERATIONS ===
    
    def get_failures_by_goal(
        self,
        goal_id: str,
        limit: int = 50,
        severity: FailureSeverity | None = None,
    ) -> list[FailureRecord]:
        """
        Get failures for a goal, most recent first.
        
        Args:
            goal_id: The goal ID to query
            limit: Maximum number of failures to return
            severity: Optional filter by severity
            
        Returns:
            List of FailureRecord objects
        """
        failure_ids = self._get_index("by_goal", goal_id)
        
        failures = []
        for fid in failure_ids:
            failure = self.get_failure(goal_id, fid)
            if failure:
                if severity is None or failure.severity == severity:
                    failures.append(failure)
        
        # Sort by timestamp descending
        failures.sort(key=lambda f: f.timestamp, reverse=True)
        return failures[:limit]
    
    def get_failures_by_node(self, node_id: str, limit: int = 50) -> list[FailureRecord]:
        """Get all failures for a specific node."""
        failure_ids = self._get_index("by_node", node_id)
        
        failures = []
        for fid in failure_ids:
            # Need to find which goal this failure belongs to
            failure = self._find_failure_by_id(fid)
            if failure:
                failures.append(failure)
        
        failures.sort(key=lambda f: f.timestamp, reverse=True)
        return failures[:limit]
    
    def get_failures_by_error_type(self, error_type: str, limit: int = 50) -> list[FailureRecord]:
        """Find failures by exception/error type."""
        failure_ids = self._get_index("by_error_type", self._sanitize_key(error_type))
        
        failures = []
        for fid in failure_ids:
            failure = self._find_failure_by_id(fid)
            if failure:
                failures.append(failure)
        
        failures.sort(key=lambda f: f.timestamp, reverse=True)
        return failures[:limit]
    
    def get_failures_by_run(self, run_id: str) -> list[FailureRecord]:
        """Get all failures for a specific run."""
        failure_ids = self._get_index("by_run", run_id)
        
        failures = []
        for fid in failure_ids:
            failure = self._find_failure_by_id(fid)
            if failure:
                failures.append(failure)
        
        failures.sort(key=lambda f: f.timestamp)
        return failures
    
    def get_recent_failures(self, limit: int = 20) -> list[FailureRecord]:
        """Get most recent failures across all goals."""
        all_failures = []
        
        goals_dir = self.base_path / "failures"
        if goals_dir.exists():
            for goal_dir in goals_dir.iterdir():
                if goal_dir.is_dir():
                    failures = self.get_failures_by_goal(goal_dir.name, limit=limit)
                    all_failures.extend(failures)
        
        all_failures.sort(key=lambda f: f.timestamp, reverse=True)
        return all_failures[:limit]
    
    # === STATISTICS ===
    
    def get_failure_stats(self, goal_id: str, use_cache: bool = True) -> FailureStats:
        """
        Get failure statistics for a goal.
        
        Args:
            goal_id: The goal ID to analyze
            use_cache: Whether to use cached stats if available
            
        Returns:
            FailureStats with counts and patterns
        """
        # Check cache
        stats_path = self.base_path / "stats" / f"{goal_id}_stats.json"
        if use_cache and stats_path.exists():
            with open(stats_path) as f:
                return FailureStats.model_validate_json(f.read())
        
        # Compute stats
        failures = self.get_failures_by_goal(goal_id, limit=1000)
        
        if not failures:
            return FailureStats(goal_id=goal_id)
        
        # Count by category
        by_severity = Counter(f.severity.value for f in failures)
        by_source = Counter(f.source.value for f in failures)
        by_error_type = Counter(f.error_type for f in failures)
        by_node = Counter(f.node_id for f in failures if f.node_id)
        
        # Top errors
        top_errors = [
            {"error_type": err, "count": count}
            for err, count in by_error_type.most_common(5)
        ]
        
        # Top failing nodes
        top_failing_nodes = [
            {"node_id": node, "count": count}
            for node, count in by_node.most_common(5)
        ]
        
        stats = FailureStats(
            goal_id=goal_id,
            total_failures=len(failures),
            by_severity=dict(by_severity),
            by_source=dict(by_source),
            by_error_type=dict(by_error_type),
            by_node=dict(by_node),
            first_failure=min(f.timestamp for f in failures),
            last_failure=max(f.timestamp for f in failures),
            top_errors=top_errors,
            top_failing_nodes=top_failing_nodes,
        )
        
        # Cache stats
        with open(stats_path, "w") as f:
            f.write(stats.model_dump_json(indent=2))
        
        return stats
    
    def get_similar_failures(
        self,
        failure_id: str,
        goal_id: str,
        limit: int = 10,
    ) -> list[FailureRecord]:
        """
        Find failures similar to the given one.
        
        Similarity is based on:
        - Same error type
        - Same node
        - Similar input keys
        
        Args:
            failure_id: The failure to find similar ones for
            goal_id: The goal ID
            limit: Maximum results
            
        Returns:
            List of similar failures
        """
        target = self.get_failure(goal_id, failure_id)
        if not target:
            return []
        
        candidates = []
        
        # Get failures with same error type
        same_error = self.get_failures_by_error_type(target.error_type, limit=100)
        
        for failure in same_error:
            if failure.id == target.id:
                continue
            
            score = 0
            
            # Same error type (already matched)
            score += 2
            
            # Same node
            if failure.node_id == target.node_id:
                score += 3
            
            # Same goal
            if failure.goal_id == target.goal_id:
                score += 1
            
            # Similar input keys
            target_keys = set(target.input_data.keys())
            failure_keys = set(failure.input_data.keys())
            if target_keys and failure_keys:
                overlap = len(target_keys & failure_keys) / len(target_keys | failure_keys)
                score += overlap * 2
            
            candidates.append((score, failure))
        
        # Sort by score descending
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [f for _, f in candidates[:limit]]
    
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
    
    def _sanitize_key(self, key: str) -> str:
        """Sanitize a key for use in filenames."""
        # Replace problematic characters
        return key.replace("/", "_").replace("\\", "_").replace(":", "_")
    
    def _find_failure_by_id(self, failure_id: str) -> FailureRecord | None:
        """Find a failure by ID across all goals."""
        goals_dir = self.base_path / "failures"
        if not goals_dir.exists():
            return None
        
        for goal_dir in goals_dir.iterdir():
            if goal_dir.is_dir():
                failure = self.get_failure(goal_dir.name, failure_id)
                if failure:
                    return failure
        return None
    
    # === UTILITY ===
    
    def list_all_goals(self) -> list[str]:
        """List all goal IDs that have failures."""
        goals_dir = self.base_path / "indexes" / "by_goal"
        return [f.stem for f in goals_dir.glob("*.json")]
    
    def get_storage_stats(self) -> dict[str, Any]:
        """Get storage statistics."""
        goals = self.list_all_goals()
        total_failures = sum(len(self._get_index("by_goal", g)) for g in goals)
        
        by_severity = {}
        for severity in FailureSeverity:
            count = len(self._get_index("by_severity", severity.value))
            if count > 0:
                by_severity[severity.value] = count
        
        return {
            "total_goals": len(goals),
            "total_failures": total_failures,
            "by_severity": by_severity,
            "storage_path": str(self.base_path),
        }
    
    def clear_all(self, goal_id: str | None = None) -> int:
        """
        Clear all failure records.
        
        Args:
            goal_id: If provided, only clear failures for this goal
            
        Returns:
            Number of failures deleted
        """
        count = 0
        
        if goal_id:
            failures = self.get_failures_by_goal(goal_id, limit=10000)
            for failure in failures:
                if self.delete_failure(goal_id, failure.id):
                    count += 1
        else:
            for gid in self.list_all_goals():
                failures = self.get_failures_by_goal(gid, limit=10000)
                for failure in failures:
                    if self.delete_failure(gid, failure.id):
                        count += 1
        
        return count
