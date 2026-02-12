"""
TraceIndexer: Builds trace index from runtime logs.

Follows Hive patterns:
- Async I/O with asyncio.to_thread()
- Non-fatal error handling
- Type safety with Pydantic models
- Clean data flow

Reference: core/framework/runtime/runtime_log_store.py
"""

import asyncio
import json
import logging
from pathlib import Path

from framework.debugging.index_store import IndexStore
from framework.debugging.trace_index import TraceIndex
from framework.runtime.runtime_log_schemas import (
    NodeDetail,
    RunSummaryLog,
)

logger = logging.getLogger(__name__)


class TraceIndexer:
    """
    Builds trace index from L1/L2/L3 runtime logs.

    Scans session directories, reads runtime logs, extracts metadata,
    and builds an indexed catalog for fast querying.

    Follows Hive patterns:
    - Async I/O with asyncio.to_thread()
    - Non-fatal error handling (logs, doesn't crash)
    - Type safety with Pydantic models

    Reference: framework/runtime/runtime_log_store.py
    """

    def __init__(self, agent_base_path: Path):
        """
        Initialize trace indexer.

        Args:
            agent_base_path: Base path for agent storage
                            (e.g., ~/.hive/agents/{agent_name})
        """
        self.agent_base_path = Path(agent_base_path)
        self.sessions_dir = self.agent_base_path / "sessions"

    async def index_all_sessions(self, store: IndexStore) -> dict[str, int]:
        """
        Index all sessions and store in IndexStore.

        Scans sessions directory, reads L1/L2/L3 logs, creates TraceIndex
        entries, and stores them.

        Args:
            store: IndexStore to populate

        Returns:
            dict with counts: {"indexed": N, "skipped": M, "errors": K}
        """
        stats = {"indexed": 0, "skipped": 0, "errors": 0}

        if not self.sessions_dir.exists():
            logger.info("No sessions directory found at %s", self.sessions_dir)
            return stats

        # Discover all session directories
        session_dirs = await self._discover_sessions()
        logger.info(f"Found {len(session_dirs)} sessions to index")

        # Index each session
        for session_dir in session_dirs:
            try:
                trace = await self.index_session(session_dir)
                if trace:
                    store.add(trace)
                    stats["indexed"] += 1
                else:
                    stats["skipped"] += 1
            except Exception:
                logger.exception("Failed to index session %s (non-fatal)", session_dir.name)
                stats["errors"] += 1

        return stats

    async def index_session(self, session_dir: Path) -> TraceIndex | None:
        """
        Index a single session directory.

        Reads L1 summary.json and L2 details.jsonl to extract metadata.

        Args:
            session_dir: Path to session directory

        Returns:
            TraceIndex if successful, None if logs don't exist or are incomplete
        """
        session_id = session_dir.name
        logs_dir = session_dir / "logs"

        # Check if logs directory exists
        if not logs_dir.exists():
            logger.debug("No logs directory for session %s", session_id)
            return None

        # Read L1 summary
        summary = await self._read_summary(logs_dir)
        if summary is None:
            # In-progress or incomplete session
            logger.debug("No summary.json for session %s", session_id)
            return None

        # Read L2 details for additional metrics
        details = await self._read_details(logs_dir)

        # Extract agent_id from session_id or summary
        agent_id = summary.agent_id or "unknown"

        # Aggregate metrics from L2
        total_input_tokens = summary.total_input_tokens
        total_output_tokens = summary.total_output_tokens
        total_latency_ms = summary.duration_ms
        node_count = summary.total_nodes_executed
        node_ids = summary.node_path

        # Find error information
        error_message = None
        failed_node_id = None

        if details:
            # Find first failed node
            for detail in details:
                if not detail.success or detail.error:
                    error_message = detail.error or f"Node {detail.node_id} failed"
                    failed_node_id = detail.node_id
                    break

        # Build paths
        summary_path = str(logs_dir / "summary.json")
        details_path = str(logs_dir / "details.jsonl")
        tool_logs_path = str(logs_dir / "tool_logs.jsonl")

        # Create TraceIndex
        trace = TraceIndex(
            run_id=summary.run_id,
            agent_id=agent_id,
            session_id=session_id,
            status=summary.status,
            execution_quality=summary.execution_quality or "clean",
            total_latency_ms=total_latency_ms,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            node_count=node_count,
            error_message=error_message,
            failed_node_id=failed_node_id,
            summary_path=summary_path,
            details_path=details_path,
            tool_logs_path=tool_logs_path,
            node_ids=node_ids,
        )

        return trace

    async def _discover_sessions(self) -> list[Path]:
        """
        Discover all session directories.

        Follows Hive pattern: asyncio.to_thread for blocking I/O.

        Returns:
            List of session directory paths
        """

        def _scan() -> list[Path]:
            """Blocking scan operation."""
            if not self.sessions_dir.exists():
                return []

            sessions = []
            for item in self.sessions_dir.iterdir():
                if item.is_dir() and item.name.startswith("session_"):
                    sessions.append(item)

            return sessions

        return await asyncio.to_thread(_scan)

    async def _read_summary(self, logs_dir: Path) -> RunSummaryLog | None:
        """
        Read L1 summary.json.

        Follows Hive pattern: asyncio.to_thread for blocking I/O.

        Args:
            logs_dir: Path to logs directory

        Returns:
            RunSummaryLog if successful, None otherwise
        """

        def _read() -> RunSummaryLog | None:
            """Blocking read operation."""
            summary_path = logs_dir / "summary.json"
            if not summary_path.exists():
                return None

            try:
                with open(summary_path) as f:
                    data = json.load(f)
                return RunSummaryLog(**data)
            except Exception:
                logger.exception("Failed to read summary from %s (non-fatal)", summary_path)
                return None

        return await asyncio.to_thread(_read)

    async def _read_details(self, logs_dir: Path) -> list[NodeDetail] | None:
        """
        Read L2 details.jsonl.

        Follows Hive pattern: asyncio.to_thread for blocking I/O.

        Args:
            logs_dir: Path to logs directory

        Returns:
            List of NodeDetail if successful, None otherwise
        """

        def _read() -> list[NodeDetail] | None:
            """Blocking read operation."""
            details_path = logs_dir / "details.jsonl"
            if not details_path.exists():
                return None

            details = []
            try:
                with open(details_path) as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            data = json.loads(line)
                            details.append(NodeDetail(**data))
                        except Exception:
                            # Skip corrupt lines (Hive pattern)
                            logger.debug("Skipping corrupt line in %s", details_path)
                            continue
                return details
            except Exception:
                logger.exception("Failed to read details from %s (non-fatal)", details_path)
                return None

        return await asyncio.to_thread(_read)
