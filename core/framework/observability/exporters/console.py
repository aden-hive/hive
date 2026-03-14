"""
Console exporter for development and debugging.

This exporter prints formatted observability events to the console,
making it easy to monitor agent execution during development.
"""

import sys
from datetime import datetime
from typing import Any

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


class ConsoleExporter(ObservabilityHooks):
    """
    Console exporter that prints observability events to stdout.

    This exporter is designed for development and debugging, providing
    human-readable output of all agent lifecycle events.

    Attributes:
        verbose: If True, include detailed information like full arguments
            and outputs. If False, show summarized information.
        colors: If True, use ANSI colors in output.
        stream: Output stream (default: stdout).

    Example:
        exporter = ConsoleExporter(verbose=True)
        hooks = CompositeHooks([exporter])
    """

    COLORS = {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "blue": "\033[34m",
        "cyan": "\033[36m",
        "magenta": "\033[35m",
    }

    def __init__(
        self,
        verbose: bool = False,
        colors: bool = True,
        stream: Any = None,
    ) -> None:
        """
        Initialize the console exporter.

        Args:
            verbose: Enable verbose output with full details.
            colors: Enable ANSI color codes in output.
            stream: Output stream (defaults to stdout).
        """
        self.verbose = verbose
        self.colors = colors and self._supports_color()
        self.stream = stream or sys.stdout

    def _supports_color(self) -> bool:
        """Check if the terminal supports colors."""
        return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

    def _color(self, text: str, color: str) -> str:
        """Apply color to text if colors are enabled."""
        if not self.colors:
            return text
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def _timestamp(self) -> str:
        """Get formatted timestamp for current time."""
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    def _print(self, message: str) -> None:
        """Print a message to the output stream."""
        timestamp = self._color(self._timestamp(), "dim")
        self.stream.write(f"{timestamp} {message}\n")
        self.stream.flush()

    def _truncate(self, text: str, max_len: int = 100) -> str:
        """Truncate text to max_len characters."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    async def on_run_start(self, context: RunContext) -> None:
        goal = self._color(context.goal_id, "cyan")
        desc = self._truncate(context.goal_description, 50)
        if desc:
            desc = f" - {desc}"
        self._print(f"{self._color('[RUN]', 'bold')} Started: {goal}{desc}")

    async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
        status = "SUCCESS" if outcome.success else "FAILED"
        status_color = "green" if outcome.success else "red"
        tokens = f" | {outcome.total_tokens} tokens" if outcome.total_tokens else ""
        steps = f" | {outcome.steps_executed} steps" if outcome.steps_executed else ""
        self._print(
            f"{self._color('[RUN]', 'bold')} Completed: "
            f"{self._color(status, status_color)}{tokens}{steps}"
        )

    async def on_node_start(self, context: NodeContext) -> None:
        node = self._color(context.node_id, "magenta")
        node_type = self._color(f"({context.node_type})", "dim")
        self._print(f"  {self._color('[NODE]', 'blue')} {node} {node_type}")

    async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
        node = self._color(context.node_id, "magenta")
        status = "✓" if result.success else "✗"
        status_color = "green" if result.success else "red"

        details = ""
        if result.tokens_used:
            details += f" | {result.tokens_used} tokens"
        if result.latency_ms:
            details += f" | {result.latency_ms}ms"

        self._print(
            f"  {self._color('[NODE]', 'blue')} {node}: "
            f"{self._color(status, status_color)}{details}"
        )

        if self.verbose and result.output:
            for key, value in result.output.items():
                val_str = self._truncate(str(value), 60)
                self._print(f"    └─ {key}: {val_str}")

    async def on_node_error(
        self, context: NodeContext, error: str, result: NodeResult | None = None
    ) -> None:
        node = self._color(context.node_id, "magenta")
        error_msg = self._truncate(error, 80)
        self._print(
            f"  {self._color('[NODE]', 'blue')} {node}: {self._color('ERROR', 'red')} - {error_msg}"
        )

    async def on_decision_made(self, decision: DecisionData) -> None:
        if not self.verbose:
            return
        node = self._color(decision.node_id, "magenta")
        chosen = self._color(decision.chosen, "cyan")
        intent = self._truncate(decision.intent, 40)
        self._print(f"  {self._color('[DECISION]', 'yellow')} {node}: {intent} → {chosen}")

    async def on_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        context: NodeContext,
        is_error: bool = False,
        latency_ms: int = 0,
    ) -> None:
        status = "ERROR" if is_error else "OK"
        status_color = "red" if is_error else "green"
        tool = self._color(tool_name, "cyan")

        details = ""
        if latency_ms:
            details += f" ({latency_ms}ms)"

        if self.verbose:
            args_str = self._truncate(str(args), 40)
            self._print(
                f"    {self._color('[TOOL]', 'dim')} {tool}({args_str}) → "
                f"{self._color(status, status_color)}{details}"
            )
        else:
            self._print(
                f"    {self._color('[TOOL]', 'dim')} {tool} → "
                f"{self._color(status, status_color)}{details}"
            )

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
        model_str = self._color(model, "cyan")
        tokens = f"{input_tokens}→{output_tokens}"
        if cached_tokens:
            tokens += f" ({cached_tokens} cached)"

        details = f" | {tokens}"
        if latency_ms:
            details += f" | {latency_ms}ms"

        if error:
            self._print(
                f"    {self._color('[LLM]', 'dim')} {model_str}: "
                f"{self._color('ERROR', 'red')} - {self._truncate(error, 40)}"
            )
        else:
            self._print(f"    {self._color('[LLM]', 'dim')} {model_str}{details}")

    async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
        if not self.verbose:
            return
        source = self._color(data.source_node, "dim")
        target = self._color(data.target_node, "cyan")
        cond = f" [{data.condition}]" if data.condition else ""
        self._print(f"  {self._color('[EDGE]', 'dim')} {source} → {target}{cond}")

    async def on_retry(self, data: RetryData) -> None:
        node = self._color(data.node_id, "magenta")
        error = self._truncate(data.error, 40)
        self._print(
            f"  {self._color('[RETRY]', 'yellow')} {node}: "
            f"attempt {data.retry_count}/{data.max_retries} - {error}"
        )
