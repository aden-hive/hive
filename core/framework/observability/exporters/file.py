"""
File exporter for JSON Lines format.

This exporter writes observability events to a file in JSON Lines format,
suitable for log aggregation systems, local analysis, and debugging.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from framework.observability.hooks import ObservabilityHooks
from framework.observability.types import (
    DecisionData,
    EdgeTraversalData,
    NodeContext,
    NodeResult,
    RetryData,
    RunContext,
    RunOutcome,
)


class FileExporter(ObservabilityHooks):
    """
    File exporter that writes observability events to JSON Lines format.

    Each event is written as a single line of JSON, making it easy to:
    - Process with log aggregation tools (ELK, Loki, etc.)
    - Analyze with command-line tools (jq, grep, etc.)
    - Import into data analysis tools (pandas, etc.)

    Attributes:
        path: Path to the output file.
        include_sensitive: If True, include potentially sensitive data
            like input/output content.
        flush_on_write: If True, flush after each write (slower but safer).

    Example:
        exporter = FileExporter(path="logs/observability.jsonl")
        hooks = CompositeHooks([exporter])
    """

    def __init__(
        self,
        path: Path | str,
        include_sensitive: bool = False,
        flush_on_write: bool = True,
    ) -> None:
        """
        Initialize the file exporter.

        Args:
            path: Path to the output file. Parent directories will be created.
            include_sensitive: Whether to include sensitive data in output.
            flush_on_write: Whether to flush after each write.
        """
        self.path = Path(path) if isinstance(path, str) else path
        self.include_sensitive = include_sensitive
        self.flush_on_write = flush_on_write
        self._file: IO[str] | None = None

    def _get_file(self) -> IO[str]:
        """Get or open the output file."""
        if self._file is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.path, "a", encoding="utf-8")
        return self._file

    def _write_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Write an event to the file."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            **data,
        }
        line = json.dumps(event, default=str, separators=(",", ":"))
        f = self._get_file()
        f.write(line + "\n")
        if self.flush_on_write:
            f.flush()

    async def on_run_start(self, context: RunContext) -> None:
        data = context.to_dict()
        if not self.include_sensitive:
            data.pop("input_data", None)
        self._write_event("run_start", data)

    async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
        data = {
            "run_id": context.run_id,
            "goal_id": context.goal_id,
            **outcome.to_dict(),
        }
        if not self.include_sensitive:
            data.pop("output_data", None)
        self._write_event("run_complete", data)

    async def on_node_start(self, context: NodeContext) -> None:
        data = context.to_dict()
        if not self.include_sensitive:
            data.pop("input_data", None)
        self._write_event("node_start", data)

    async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
        data = {
            "run_id": context.run_id,
            **result.to_dict(),
        }
        if not self.include_sensitive:
            data.pop("output", None)
        self._write_event("node_complete", data)

    async def on_node_error(
        self, context: NodeContext, error: str, result: NodeResult | None = None
    ) -> None:
        data = {
            "run_id": context.run_id,
            "node_id": context.node_id,
            "error": error,
        }
        if result:
            data["tokens_used"] = result.tokens_used
            data["latency_ms"] = result.latency_ms
        self._write_event("node_error", data)

    async def on_decision_made(self, decision: DecisionData) -> None:
        self._write_event("decision_made", decision.to_dict())

    async def on_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        context: NodeContext,
        is_error: bool = False,
        latency_ms: int = 0,
    ) -> None:
        data = {
            "run_id": context.run_id,
            "node_id": context.node_id,
            "tool_name": tool_name,
            "is_error": is_error,
            "latency_ms": latency_ms,
        }
        if self.include_sensitive:
            data["args"] = args
            data["result"] = result[:1000]
        self._write_event("tool_call", data)

    async def on_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        context: NodeContext,
        latency_ms: int = 0,
        cached_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        data = {
            "run_id": context.run_id,
            "node_id": context.node_id,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "latency_ms": latency_ms,
        }
        if error:
            data["error"] = error
        self._write_event("llm_call", data)

    async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
        self._write_event("edge_traversed", data.to_dict())

    async def on_retry(self, data: RetryData) -> None:
        self._write_event("retry", data.to_dict())

    def close(self) -> None:
        """Close the file handle."""
        if self._file is not None:
            self._file.close()
            self._file = None

    def __del__(self) -> None:
        """Ensure file is closed on deletion."""
        self.close()
