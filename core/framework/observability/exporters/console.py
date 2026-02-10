"""Console exporter — pretty-printed real-time observability for development.

Outputs lifecycle events in a structured, colorized format to stderr
for easy debugging during local development.

Usage::

    from framework.observability.exporters.console import ConsoleExporter
    from framework.observability.hooks import CompositeHooks

    runtime = Runtime(
        storage_path="./logs",
        observability_hooks=ConsoleExporter(),
    )
"""

from __future__ import annotations

import sys
from datetime import datetime
from typing import TextIO

from framework.observability.types import (
    DecisionEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    NodeStartEvent,
    RunCompleteEvent,
    RunStartEvent,
    ToolCallEvent,
)

# ANSI color codes
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BLUE = "\033[34m"
_CYAN = "\033[36m"
_MAGENTA = "\033[35m"


class ConsoleExporter:
    """Pretty-prints observability events to the console.

    Args:
        stream: Output stream (default: stderr)
        verbose: If True, include extra detail like reasoning and input data
        color: If True, use ANSI colors (default: True)
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        verbose: bool = False,
        color: bool = True,
    ) -> None:
        self._stream = stream or sys.stderr
        self._verbose = verbose
        self._color = color

    def _ts(self) -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _c(self, code: str, text: str) -> str:
        if not self._color:
            return text
        return f"{code}{text}{_RESET}"

    def _write(self, line: str) -> None:
        self._stream.write(line + "\n")
        self._stream.flush()

    async def on_run_start(self, event: RunStartEvent) -> None:
        self._write(
            f"{self._c(_DIM, self._ts())} "
            f"{self._c(_BOLD + _BLUE, '[RUN]')} "
            f"Started: {self._c(_BOLD, event.goal_id)} "
            f"{self._c(_DIM, f'(run={event.run_id})')}"
        )

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        status_color = _GREEN if event.status == "success" else _RED
        self._write(
            f"{self._c(_DIM, self._ts())} "
            f"{self._c(_BOLD + _BLUE, '[RUN]')} "
            f"Completed: {self._c(status_color, event.status.upper())} "
            f"{self._c(_DIM, f'({event.duration_ms}ms)')}"
        )

    async def on_node_start(self, event: NodeStartEvent) -> None:
        self._write(
            f"{self._c(_DIM, self._ts())} "
            f"{self._c(_CYAN, '[NODE]')} "
            f"{self._c(_BOLD, event.node_name)}: "
            f"Executing {self._c(_DIM, f'({event.node_type})')}"
        )

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        if event.success:
            self._write(
                f"{self._c(_DIM, self._ts())} "
                f"{self._c(_GREEN, '[NODE]')} "
                f"{self._c(_BOLD, event.node_name)}: "
                f"{self._c(_GREEN, '✓ Success')} "
                f"{self._c(_DIM, f'({event.latency_ms}ms, {event.tokens_used} tokens)')}"
            )
        else:
            self._write(
                f"{self._c(_DIM, self._ts())} "
                f"{self._c(_RED, '[NODE]')} "
                f"{self._c(_BOLD, event.node_name)}: "
                f"{self._c(_RED, '✗ Failed')} "
                f"{self._c(_DIM, f'({event.latency_ms}ms)')}"
            )

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        self._write(
            f"{self._c(_DIM, self._ts())} "
            f"{self._c(_RED, '[ERROR]')} "
            f"{self._c(_BOLD, event.node_name)}: "
            f"{self._c(_RED, event.error)}"
        )

    async def on_decision_made(self, event: DecisionEvent) -> None:
        line = (
            f"{self._c(_DIM, self._ts())} "
            f"{self._c(_MAGENTA, '[DECISION]')} "
            f"{event.intent} → {self._c(_BOLD, event.chosen)}"
        )
        if self._verbose:
            line += f" {self._c(_DIM, f'(reason: {event.reasoning})')}"
        self._write(line)

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        status = self._c(_RED, "✗") if event.is_error else self._c(_GREEN, "✓")
        self._write(
            f"{self._c(_DIM, self._ts())} "
            f"{self._c(_YELLOW, '[TOOL]')} "
            f"{event.tool_name} {status} "
            f"{self._c(_DIM, f'({event.latency_ms}ms)')}"
        )
