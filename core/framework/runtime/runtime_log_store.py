"""File-based storage for runtime logs.

Each run gets its own directory under ``runs/``. No shared mutable index —
``list_runs()`` scans the directory and loads summary.json from each run.
This eliminates concurrency issues when parallel EventLoopNodes write
simultaneously.

L2 (details) and L3 (tool logs) use JSONL (one JSON object per line) for
incremental append-on-write. This provides crash resilience — data is on
disk as soon as it's logged, not only at end_run(). L1 (summary) is still
written once at end as a regular JSON file since it aggregates L2.

Storage layout (current)::

    {base_path}/
      sessions/
        {session_id}/
          logs/
            summary.json     # Level 1 — written once at end
            details.jsonl    # Level 2 — appended per node completion
            tool_logs.jsonl  # Level 3 — appended per step
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from framework.runtime.runtime_log_schemas import (
    NodeDetail,
    NodeStepLog,
    RunDetailsLog,
    RunSummaryLog,
    RunToolLogs,
)

logger = logging.getLogger(__name__)


class RuntimeLogStore:
    """Persists runtime logs at three levels. Thread-safe via per-run directories."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path
        # Note: _runs_dir is determined per-run_id by _get_run_dir()

    def _get_run_dir(self, run_id: str) -> Path:
        """Determine run directory path based on run_id format.

        - New format (session_*): {storage_root}/sessions/{run_id}/logs/
        - Old format (anything else): {base_path}/runs/{run_id}/ (deprecated)
        """
        if run_id.startswith("session_"):
            is_runtime_logs = self._base_path.name == "runtime_logs"
            root = self._base_path.parent if is_runtime_logs else self._base_path
            return root / "sessions" / run_id / "logs"
        import warnings

        warnings.warn(
            f"Reading logs from deprecated location for run_id={run_id}. "
            "New sessions use unified storage at sessions/session_*/logs/",
            DeprecationWarning,
            stacklevel=3,
        )
        return self._base_path / "runs" / run_id

    # -------------------------------------------------------------------
    # Incremental write (sync — called from locked sections)
    # -------------------------------------------------------------------

    def ensure_run_dir(self, run_id: str) -> None:
        """Create the run directory immediately. Called by start_run()."""
        run_dir = self._get_run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

    def append_step(self, run_id: str, step: NodeStepLog) -> None:
        """Append one JSONL line to tool_logs.jsonl. Sync."""
        path = self._get_run_dir(run_id) / "tool_logs.jsonl"
        line = json.dumps(step.model_dump(), ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def append_node_detail(self, run_id: str, detail: NodeDetail) -> None:
        """Append one JSONL line to details.jsonl. Sync."""
        path = self._get_run_dir(run_id) / "details.jsonl"
        line = json.dumps(detail.model_dump(), ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def read_node_details_sync(self, run_id: str) -> list[NodeDetail]:
        """Read details.jsonl back into a list of NodeDetail. Sync.

        Used by end_run() to aggregate L2 into L1. Skips corrupt lines.
        """
        path = self._get_run_dir(run_id) / "details.jsonl"
        return _read_jsonl_as_models(path, NodeDetail)

    # -------------------------------------------------------------------
    # Summary write (async — called from end_run)
    # -------------------------------------------------------------------

    async def save_summary(self, run_id: str, summary: RunSummaryLog) -> None:
        """Write summary.json atomically. Called once at end_run()."""
        run_dir = self._get_run_dir(run_id)
        await asyncio.to_thread(run_dir.mkdir, parents=True, exist_ok=True)
        await self._write_json(run_dir / "summary.json", summary.model_dump())

    # -------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------

    async def load_summary(self, run_id: str) -> RunSummaryLog | None:
        """Load Level 1 summary for a specific run."""
        data = await self._read_json(self._get_run_dir(run_id) / "summary.json")
        return RunSummaryLog(**data) if data is not None else None

    async def load_details(self, run_id: str) -> RunDetailsLog | None:
        """Load Level 2 details from details.jsonl for a specific run."""
        path = self._get_run_dir(run_id) / "details.jsonl"

        def _read() -> RunDetailsLog | None:
            if not path.exists():
                return None
            nodes = _read_jsonl_as_models(path, NodeDetail)
            return RunDetailsLog(run_id=run_id, nodes=nodes)

        return await asyncio.to_thread(_read)

    async def load_tool_logs(self, run_id: str) -> RunToolLogs | None:
        """Load Level 3 tool logs from tool_logs.jsonl for a specific run."""
        path = self._get_run_dir(run_id) / "tool_logs.jsonl"

        def _read() -> RunToolLogs | None:
            if not path.exists():
                return None
            steps = _read_jsonl_as_models(path, NodeStepLog)
            return RunToolLogs(run_id=run_id, steps=steps)

        return await asyncio.to_thread(_read)

    async def list_runs(
        self,
        status: str = "",
        needs_attention: bool | None = None,
        limit: int = 20,
    ) -> list[RunSummaryLog]:
        """Scan both old and new directory structures, load summaries, filter, and sort.

        Scans:
        - Old: base_path/runs/{run_id}/
        - New: base_path/sessions/{session_id}/logs/

        Directories without summary.json are treated as in-progress runs and
        get a synthetic summary with status="in_progress".
        """
        entries = await asyncio.to_thread(self._scan_run_dirs)
        summaries: list[RunSummaryLog] = []

        for run_id in entries:
            summary = await self.load_summary(run_id)
            if summary is None:
                # In-progress run: no summary.json yet. Synthesize one.
                run_dir = self._get_run_dir(run_id)
                if not run_dir.is_dir():
                    continue
                summary = RunSummaryLog(
                    run_id=run_id,
                    status="in_progress",
                    started_at=_infer_started_at(run_id),
                )
            if status and status != "needs_attention" and summary.status != status:
                continue
            if status == "needs_attention" and not summary.needs_attention:
                continue
            if needs_attention is not None and summary.needs_attention != needs_attention:
                continue
            summaries.append(summary)

        # Sort by started_at descending (most recent first)
        summaries.sort(key=lambda s: s.started_at, reverse=True)
        return summaries[:limit]

    # -------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------

    def _scan_run_dirs(self) -> list[str]:
        """Return list of run_id directory names from both old and new locations.

        Scans:
        - New: base_path/sessions/{session_id}/logs/ (preferred)
        - Old: base_path/runs/{run_id}/ (deprecated, backward compatibility)

        Returns run_ids/session_ids. Includes all directories, not just those
        with summary.json, so in-progress runs are visible.
        """
        run_ids = []

        # Scan new location: base_path/sessions/{session_id}/logs/
        # Determine the correct base path for sessions
        is_runtime_logs = self._base_path.name == "runtime_logs"
        root = self._base_path.parent if is_runtime_logs else self._base_path
        sessions_dir = root / "sessions"

        if sessions_dir.exists():
            for session_dir in sessions_dir.iterdir():
                if session_dir.is_dir() and session_dir.name.startswith("session_"):
                    logs_dir = session_dir / "logs"
                    if logs_dir.exists() and logs_dir.is_dir():
                        run_ids.append(session_dir.name)

        # Scan old location: base_path/runs/ (deprecated)
        old_runs_dir = self._base_path / "runs"
        if old_runs_dir.exists():
            old_ids = [d.name for d in old_runs_dir.iterdir() if d.is_dir()]
            if old_ids:
                import warnings

                warnings.warn(
                    f"Found {len(old_ids)} runs in deprecated location. "
                    "Consider migrating to unified session storage.",
                    DeprecationWarning,
                    stacklevel=3,
                )
            run_ids.extend(old_ids)

        return run_ids

    @staticmethod
    async def _write_json(path: Path, data: dict) -> None:
        """Write JSON atomically: write to .tmp then rename."""
        tmp = path.with_suffix(".tmp")
        content = json.dumps(data, indent=2, ensure_ascii=False)

        def _write() -> None:
            tmp.write_text(content, encoding="utf-8")
            tmp.rename(path)

        await asyncio.to_thread(_write)

    @staticmethod
    async def _read_json(path: Path) -> dict | None:
        """Read and parse a JSON file. Returns None if missing or corrupt."""

        def _read() -> dict | None:
            if not path.exists():
                return None
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to read %s: %s", path, e)
                return None

        return await asyncio.to_thread(_read)


# -------------------------------------------------------------------
# Module-level helpers
# -------------------------------------------------------------------


def _read_jsonl_as_models(path: Path, model_cls: type) -> list:
    """Parse a JSONL file into a list of Pydantic model instances.

    Skips blank lines and corrupt JSON lines (partial writes from crashes).
    """
    results = []
    if not path.exists():
        return results
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    results.append(model_cls(**data))
                except (json.JSONDecodeError, Exception) as e:
                    logger.warning("Skipping corrupt JSONL line in %s: %s", path, e)
                    continue
    except OSError as e:
        logger.warning("Failed to read %s: %s", path, e)
    return results


def _infer_started_at(run_id: str) -> str:
    """Best-effort ISO timestamp from a run_id like '20250101T120000_abc12345'."""
    try:
        ts_part = run_id.split("_")[0]  # '20250101T120000'
        dt = datetime.strptime(ts_part, "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
        return dt.isoformat()
    except (ValueError, IndexError):
        return ""
