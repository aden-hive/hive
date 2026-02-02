"""
Graph/Tree Overview Widget - Displays real agent graph structure.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import RichLog

from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import EventType


class GraphOverview(Vertical):
    """Widget to display Agent execution graph/tree with real data."""

    DEFAULT_CSS = """
    GraphOverview {
        width: 100%;
        height: 100%;
        background: $panel;
    }

    GraphOverview > RichLog {
        width: 100%;
        height: 100%;
        background: $panel;
        border: none;
        scrollbar-background: $surface;
        scrollbar-color: $primary;
    }
    """

    def __init__(self, runtime: AgentRuntime):
        super().__init__()
        self.runtime = runtime
        self.active_node = None
        self.execution_path = []

    def compose(self) -> ComposeResult:
        # Use RichLog for formatted output
        yield RichLog(id="graph-display", highlight=True, markup=True)

    def on_mount(self) -> None:
        """Display initial graph structure."""
        self._display_graph()

    def _display_graph(self) -> None:
        """Display the graph structure with nodes and entry points."""
        display = self.query_one("#graph-display", RichLog)

        # Clear and display header
        display.clear()
        display.write("[bold cyan]Agent Graph Structure[/bold cyan]\n")

        # Get graph from runtime
        graph = self.runtime.graph

        # Display graph info
        display.write(f"[dim]Graph ID:[/dim] {graph.id}")
        display.write(f"[dim]Goal:[/dim] {self.runtime.goal.description[:50]}...")
        display.write("")

        # Display entry points
        entry_points = self.runtime.get_entry_points()
        if entry_points:
            display.write("[bold]Entry Points:[/bold]")
            for ep in entry_points:
                display.write(f"  • {ep.name} → [cyan]{ep.entry_node}[/cyan]")
        else:
            display.write(f"[bold]Entry Node:[/bold] [cyan]{graph.entry_node}[/cyan]")

        display.write("")

        # Display nodes
        display.write(f"[bold]Nodes ({len(graph.nodes)}):[/bold]")
        for node in graph.nodes:
            node_type = node.type if hasattr(node, "type") else "unknown"

            # Highlight active node
            if self.active_node == node.id:
                display.write(f"  ▶ [bold green]{node.id}[/bold green] ({node_type})")
            elif node.id in self.execution_path:
                display.write(f"  ✓ [dim]{node.id}[/dim] ({node_type})")
            else:
                display.write(f"  • {node.id} ({node_type})")

        display.write("")

        # Display terminal nodes
        if graph.terminal_nodes:
            display.write("[bold]Terminal Nodes:[/bold]")
            for node_id in graph.terminal_nodes:
                display.write(f"  • [yellow]{node_id}[/yellow]")

        # Display execution status
        if self.active_node:
            display.write("")
            display.write(f"[bold green]Currently Executing:[/bold green] {self.active_node}")

        if self.execution_path:
            display.write(f"[dim]Path:[/dim] {' → '.join(self.execution_path[-5:])}")

    def update_active_node(self, node_id: str) -> None:
        """Update the currently active node."""
        self.active_node = node_id
        if node_id not in self.execution_path:
            self.execution_path.append(node_id)
        self._display_graph()

    def update_execution(self, event) -> None:
        """Update the displayed node status based on event."""
        display = self.query_one("#graph-display", RichLog)

        if event.type == EventType.NODE_STARTED:
            node_id = event.data.get("node_id")
            if node_id:
                self.update_active_node(node_id)

        elif event.type == EventType.NODE_COMPLETED:
            node_id = event.data.get("node_id")
            if node_id and node_id == self.active_node:
                self.active_node = None
                self._display_graph()

        elif event.type == EventType.EXECUTION_COMPLETED:
            display.write("")
            display.write("[bold green]✓ Execution Complete![/bold green]")
            self.active_node = None

        elif event.type == EventType.EXECUTION_FAILED:
            display.write("")
            error = event.data.get("error", "Unknown error")
            display.write(f"[bold red]✗ Execution Failed:[/bold red] {error}")
            self.active_node = None
