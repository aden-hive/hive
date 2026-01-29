from typing import Any

from framework.graph.executor import GraphExecutor
from framework.graph.node import NodeSpec


class DebugSession:
    """
    Manages a debugging session for an agent execution.

    Controls execution flow:
    - Step-by-step execution
    - Breakpoints
    - State inspection
    """

    def __init__(self, executor: GraphExecutor):
        self.executor = executor
        self.breakpoints: set[str] = set()  # Node IDs to break on
        self.pause_on_next: bool = True  # Start paused
        self.history: list[dict[str, Any]] = []  # Execution history
        self.current_step_info: dict[str, Any] | None = None

        # Hook into the executor
        # We need to modify Executor to accept a debug hook,
        # or subclass it. For now, we'll assume we can pass a callback.
        if hasattr(executor, "set_debug_hook"):
            executor.set_debug_hook(self.on_step)

    def add_breakpoint(self, node_id: str):
        """Add a breakpoint at specific node."""
        self.breakpoints.add(node_id)
        print(f"Breakpoint set at '{node_id}'")

    def remove_breakpoint(self, node_id: str):
        """Remove a breakpoint."""
        if node_id in self.breakpoints:
            self.breakpoints.remove(node_id)
            print(f"Breakpoint removing from '{node_id}'")
        else:
            print(f"No breakpoint found at '{node_id}'")

    def list_breakpoints(self):
        """List all breakpoints."""
        if not self.breakpoints:
            print("No breakpoints set.")
        else:
            print("Breakpoints:")
            for bp in self.breakpoints:
                print(f"  - {bp}")

    def on_step(
        self, node_id: str, node_spec: NodeSpec, context: dict[str, Any], memory: dict[str, Any]
    ) -> str:
        """
        Callback triggered before each node execution.

        Returns command: 'continue', 'step', 'quit' or modified state.
        """
        should_break = self.pause_on_next or node_id in self.breakpoints

        self.current_step_info = {
            "node_id": node_id,
            "node_name": node_spec.name,
            "inputs": context,
            "memory": memory,
        }

        if should_break:
            self.pause_on_next = False  # Reset single step
            return "break"

        return "continue"

    def resume(self):
        """Continue execution until next breakpoint."""
        self.pause_on_next = False

    def step(self):
        """Execute next step and pause."""
        self.pause_on_next = True

    def get_memory_snapshot(self) -> dict[str, Any]:
        """Get current memory state."""
        return self.current_step_info.get("memory", {}) if self.current_step_info else {}

    def get_context(self) -> dict[str, Any]:
        """Get current inputs/context."""
        return self.current_step_info.get("inputs", {}) if self.current_step_info else {}
