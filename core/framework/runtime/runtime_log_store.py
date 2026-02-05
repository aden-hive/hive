"""File-based storage for runtime logs.

Each run gets its own directory under ``runs/``. No shared mutable index —
``list_runs()`` scans the directory and loads summary.json from each run.
This eliminates concurrency issues when parallel EventLoopNodes write
simultaneously.

L2 (details) and L3 (tool logs) use JSONL (one JSON object per line) for
incremental append-on-write. This provides crash resilience — data is on
disk as soon as it's logged, not only at end_run(). L1 (summary) is still
written once at end as a regular JSON file since it aggregates L2.

Storage layout::

    {base_path}/
      runs/
        {run_id}/
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
        self._runs_dir = base_path / "runs"

    # -------------------------------------------------------------------
    # Incremental write (sync — called from locked sections)
    # -------------------------------------------------------------------

    def ensure_run_dir(self, run_id: str) -> None:
        """Create the run directory immediately. Called by start_run()."""
        run_dir = self._runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

    def append_step(self, run_id: str, step: NodeStepLog) -> None:
        """Append one JSONL line to tool_logs.jsonl. Sync."""
        path = self._runs_dir / run_id / "tool_logs.jsonl"
        line = json.dumps(step.model_dump(), ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def append_node_detail(self, run_id: str, detail: NodeDetail) -> None:
        """Append one JSONL line to details.jsonl. Sync."""
        path = self._runs_dir / run_id / "details.jsonl"
        line = json.dumps(detail.model_dump(), ensure_ascii=False) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)

    def read_node_details_sync(self, run_id: str) -> list[NodeDetail]:
        """Read details.jsonl back into a list of NodeDetail. Sync.

        Used by end_run() to aggregate L2 into L1. Skips corrupt lines.
        """
        path = self._runs_dir / run_id / "details.jsonl"
        return _read_jsonl_as_models(path, NodeDetail)

    # -------------------------------------------------------------------
    # Summary write (async — called from end_run)
    # -------------------------------------------------------------------

    async def save_summary(self, run_id: str, summary: RunSummaryLog) -> None:
        """Write summary.json atomically. Called once at end_run()."""
        run_dir = self._runs_dir / run_id
        await asyncio.to_thread(run_dir.mkdir, parents=True, exist_ok=True)
        await self._write_json(run_dir / "summary.json", summary.model_dump())

    # -------------------------------------------------------------------
    # Read
    # -------------------------------------------------------------------

    async def load_summary(self, run_id: str) -> RunSummaryLog | None:
        """Load Level 1 summary for a specific run."""
        data = await self._read_json(self._runs_dir / run_id / "summary.json")
        return RunSummaryLog(**data) if data is not None else None

    async def load_details(self, run_id: str) -> RunDetailsLog | None:
        """Load Level 2 details from details.jsonl for a specific run."""
        path = self._runs_dir / run_id / "details.jsonl"

        def _read() -> RunDetailsLog | None:
            if not path.exists():
                return None
            nodes = _read_jsonl_as_models(path, NodeDetail)
            return RunDetailsLog(run_id=run_id, nodes=nodes)

        return await asyncio.to_thread(_read)

    async def load_tool_logs(self, run_id: str) -> RunToolLogs | None:
        """Load Level 3 tool logs from tool_logs.jsonl for a specific run."""
        path = self._runs_dir / run_id / "tool_logs.jsonl"

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
        """Scan runs/ directory, load summaries, filter, and sort by timestamp desc.

        Directories without summary.json are treated as in-progress runs and
        get a synthetic summary with status="in_progress".
        """
        if not self._runs_dir.exists():
            return []

        entries = await asyncio.to_thread(self._scan_run_dirs)
        summaries: list[RunSummaryLog] = []

        for run_id in entries:
            summary = await self.load_summary(run_id)
            if summary is None:
                # In-progress run: no summary.json yet. Synthesize one.
                run_dir = self._runs_dir / run_id
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
        """Return list of run_id directory names (sync, for use in to_thread).

        Includes all directories, not just those with summary.json, so
        in-progress runs are visible.
        """
        if not self._runs_dir.exists():
            return []
        return [d.name for d in self._runs_dir.iterdir() if d.is_dir()]

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
