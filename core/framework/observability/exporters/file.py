"""File exporter — JSON Lines format for local analysis.

Writes one JSON object per event to a ``.jsonl`` file, suitable for
ingestion by log analysis tools or custom dashboards.

Usage::

    from framework.observability.exporters.file import FileExporter

    runtime = Runtime(
        storage_path="./logs",
        observability_hooks=FileExporter(path="./events.jsonl"),
    )
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from framework.observability.types import (
    DecisionEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    NodeStartEvent,
    RunCompleteEvent,
    RunStartEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


class FileExporter:
    """Appends lifecycle events as JSON Lines to a file.

    Thread-safe — uses a lock for concurrent writes.

    Args:
        path: Path to the JSONL output file (created if missing)
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _write_event(self, event_type: str, data: dict[str, Any]) -> None:
        record = {"event_type": event_type, **data}
        line = json.dumps(record, default=str)
        with self._lock:
            with self._path.open("a") as f:
                f.write(line + "\n")

    async def on_run_start(self, event: RunStartEvent) -> None:
        self._write_event("run_start", {
            "run_id": event.run_id,
            "goal_id": event.goal_id,
            "input_data": event.input_data,
            "timestamp": event.timestamp,
        })

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        self._write_event("run_complete", {
            "run_id": event.run_id,
            "status": event.status,
            "duration_ms": event.duration_ms,
            "total_nodes_executed": event.total_nodes_executed,
            "total_tokens": event.total_tokens,
            "timestamp": event.timestamp,
        })

    async def on_node_start(self, event: NodeStartEvent) -> None:
        self._write_event("node_start", {
            "run_id": event.run_id,
            "node_id": event.node_id,
            "node_name": event.node_name,
            "node_type": event.node_type,
            "timestamp": event.timestamp,
        })

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        self._write_event("node_complete", {
            "run_id": event.run_id,
            "node_id": event.node_id,
            "node_name": event.node_name,
            "success": event.success,
            "latency_ms": event.latency_ms,
            "tokens_used": event.tokens_used,
            "timestamp": event.timestamp,
        })

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        self._write_event("node_error", {
            "run_id": event.run_id,
            "node_id": event.node_id,
            "node_name": event.node_name,
            "error": event.error,
            "stacktrace": event.stacktrace,
            "timestamp": event.timestamp,
        })

    async def on_decision_made(self, event: DecisionEvent) -> None:
        self._write_event("decision", {
            "run_id": event.run_id,
            "decision_id": event.decision_id,
            "node_id": event.node_id,
            "intent": event.intent,
            "chosen": event.chosen,
            "reasoning": event.reasoning,
            "options_count": event.options_count,
            "timestamp": event.timestamp,
        })

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        self._write_event("tool_call", {
            "run_id": event.run_id,
            "node_id": event.node_id,
            "tool_name": event.tool_name,
            "is_error": event.is_error,
            "latency_ms": event.latency_ms,
            "timestamp": event.timestamp,
        })
