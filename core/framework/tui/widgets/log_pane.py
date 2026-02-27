"""
Log formatting utilities and LogPane widget.

The module-level functions (format_event, extract_event_text, format_python_log)
can be used by any widget that needs to render log lines without instantiating LogPane.
"""

import logging
from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container

from framework.runtime.event_bus import AgentEvent, EventType
from framework.tui.widgets.selectable_rich_log import SelectableRichLog as RichLog

# --- Module-level formatting constants ---

EVENT_FORMAT: dict[EventType, tuple[str, str]] = {
    EventType.EXECUTION_STARTED: (">>", "bold cyan"),
    EventType.EXECUTION_COMPLETED: ("<<", "bold green"),
    EventType.EXECUTION_FAILED: ("!!", "bold red"),
    EventType.TOOL_CALL_STARTED: ("->", "yellow"),
    EventType.TOOL_CALL_COMPLETED: ("<-", "green"),
    EventType.NODE_LOOP_STARTED: ("@@", "cyan"),
    EventType.NODE_LOOP_ITERATION: ("..", "dim"),
    EventType.NODE_LOOP_COMPLETED: ("@@", "dim"),
    EventType.LLM_TURN_COMPLETE: ("◆", "green"),
    EventType.NODE_STALLED: ("!!", "bold yellow"),
    EventType.NODE_INPUT_BLOCKED: ("!!", "yellow"),
    EventType.GOAL_PROGRESS: ("%%", "blue"),
    EventType.GOAL_ACHIEVED: ("**", "bold green"),
    EventType.CONSTRAINT_VIOLATION: ("!!", "bold red"),
    EventType.STATE_CHANGED: ("~~", "dim"),
    EventType.CLIENT_INPUT_REQUESTED: ("??", "magenta"),
}

LOG_LEVEL_COLORS: dict[int, str] = {
    logging.DEBUG: "dim",
    logging.INFO: "",
    logging.WARNING: "yellow",
    logging.ERROR: "red",
    logging.CRITICAL: "bold red",
}


# --- Module-level formatting functions ---


def extract_event_text(event: AgentEvent) -> str:
    """Extract human-readable text from an event's data dict."""
    et = event.type
    data = event.data

    if et == EventType.EXECUTION_STARTED:
        return "Execution started"
    elif et == EventType.EXECUTION_COMPLETED:
        return "Execution completed"
    elif et == EventType.EXECUTION_FAILED:
        return f"Execution FAILED: {data.get('error', 'unknown')}"
    elif et == EventType.TOOL_CALL_STARTED:
        return f"Tool call: {data.get('tool_name', 'unknown')}"
    elif et == EventType.TOOL_CALL_COMPLETED:
        name = data.get("tool_name", "unknown")
        if data.get("is_error"):
            preview = str(data.get("result", ""))[:80]
            return f"Tool error: {name} - {preview}"
        return f"Tool done: {name}"
    elif et == EventType.NODE_LOOP_STARTED:
        return f"Node started: {event.node_id or 'unknown'}"
    elif et == EventType.NODE_LOOP_ITERATION:
        return f"{event.node_id or 'unknown'} iteration {data.get('iteration', '?')}"
    elif et == EventType.NODE_LOOP_COMPLETED:
        return f"Node done: {event.node_id or 'unknown'}"
    elif et == EventType.NODE_STALLED:
        reason = data.get("reason", "")
        node = event.node_id or "unknown"
        return f"Node stalled: {node} - {reason}" if reason else f"Node stalled: {node}"
    elif et == EventType.NODE_INPUT_BLOCKED:
        return f"Node input blocked: {event.node_id or 'unknown'}"
    elif et == EventType.GOAL_PROGRESS:
        return f"Goal progress: {data.get('progress', '?')}"
    elif et == EventType.GOAL_ACHIEVED:
        return "Goal achieved"
    elif et == EventType.CONSTRAINT_VIOLATION:
        return f"Constraint violated: {data.get('description', 'unknown')}"
    elif et == EventType.STATE_CHANGED:
        return f"State changed: {data.get('key', 'unknown')}"
    elif et == EventType.CLIENT_INPUT_REQUESTED:
        return "Waiting for user input"
    elif et == EventType.LLM_TURN_COMPLETE:
        stop = data.get("stop_reason", "?")
        model = data.get("model", "?")
        inp = data.get("input_tokens", 0)
        out = data.get("output_tokens", 0)
        return f"{model} → {stop} ({inp}+{out} tokens)"
    else:
        return f"{et.value}: {data}"


def format_event(event: AgentEvent) -> str:
    """Format an AgentEvent as a Rich markup string with timestamp + symbol."""
    ts = event.timestamp.strftime("%H:%M:%S")
    symbol, color = EVENT_FORMAT.get(event.type, ("--", "dim"))
    text = extract_event_text(event)
    return f"[dim]{ts}[/dim] [{color}]{symbol} {text}[/{color}]"


def format_python_log(record: logging.LogRecord) -> str:
    """Format a Python log record as a Rich markup string with timestamp and severity color."""
    ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
    color = LOG_LEVEL_COLORS.get(record.levelno, "")
    msg = record.getMessage()
    if color:
        return f"[dim]{ts}[/dim] [{color}]{record.levelname}[/{color}] {msg}"
    else:
        return f"[dim]{ts}[/dim] {record.levelname} {msg}"


# --- LogPane widget (kept for backward compatibility) ---


class LogPane(Container):
    """Widget to display logs with reliable rendering."""

    DEFAULT_CSS = """
    LogPane {
        width: 100%;
        height: 100%;
    }

    LogPane > RichLog {
        width: 100%;
        height: 100%;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }
    """

    def compose(self) -> ComposeResult:
        yield RichLog(id="main-log", highlight=True, markup=True, auto_scroll=False)

    def write_event(self, event: AgentEvent) -> None:
        """Format an AgentEvent with timestamp + symbol and write to the log."""
        self.write_log(format_event(event))

    def write_python_log(self, record: logging.LogRecord) -> None:
        """Format a Python log record with timestamp and severity color."""
        self.write_log(format_python_log(record))

    def write_log(self, message: str) -> None:
        """Write a log message to the log pane."""
        try:
            if not self.is_mounted:
                return

            log = self.query_one("#main-log", RichLog)

            if not log.is_mounted:
                return

            was_at_bottom = log.is_vertical_scroll_end

            log.write(message)

            if was_at_bottom:
                log.scroll_end(animate=False)

        except Exception:
            pass
