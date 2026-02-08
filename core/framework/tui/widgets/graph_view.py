"""
Graph/Tree Overview Widget - Displays real agent graph structure.
"""

from textual.app import ComposeResult
from textual.containers import Vertical

from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import EventType
from framework.tui.widgets.selectable_rich_log import SelectableRichLog as RichLog


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
        self.active_node: str | None = None
        self.execution_path: list[str] = []
        # Per-node status strings shown next to the node in the graph display.
        # e.g. {"planner": "thinking...", "searcher": "web_search..."}
        self._node_status: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        # Use RichLog for formatted output
        yield RichLog(id="graph-display", highlight=True, markup=True)

    def on_mount(self) -> None:
        """Display initial graph structure."""
        self._display_graph()

    def _topo_order(self) -> list[str]:
        """BFS from entry_node following edges."""
        graph = self.runtime.graph
        visited: list[str] = []
        seen: set[str] = set()
        queue = [graph.entry_node]
        while queue:
            nid = queue.pop(0)
            if nid in seen:
                continue
            seen.add(nid)
            visited.append(nid)
            for edge in graph.get_outgoing_edges(nid):
                if edge.target not in seen:
                    queue.append(edge.target)
        # Append orphan nodes not reachable from entry
        for node in graph.nodes:
            if node.id not in seen:
                visited.append(node.id)
        return visited

    def _render_node_line(self, node_id: str) -> str:
        """Render a single node with status symbol and optional status text."""
        graph = self.runtime.graph
        is_terminal = node_id in (graph.terminal_nodes or [])
        is_active = node_id == self.active_node
        is_done = node_id in self.execution_path and not is_active
        status = self._node_status.get(node_id, "")

        if is_active:
            sym = "[bold green]●[/bold green]"
        elif is_done:
            sym = "[dim]✓[/dim]"
        elif is_terminal:
            sym = "[yellow]■[/yellow]"
        else:
            sym = "○"

        if is_active:
            name = f"[bold green]{node_id}[/bold green]"
        elif is_done:
            name = f"[dim]{node_id}[/dim]"
        else:
            name = node_id

        suffix = f"  [italic]{status}[/italic]" if status else ""
        return f"  {sym} {name}{suffix}"

    def _render_edges(self, node_id: str) -> list[str]:
        """Render edge connectors from this node to its targets."""
        edges = self.runtime.graph.get_outgoing_edges(node_id)
        if not edges:
            return []
        if len(edges) == 1:
            return ["  │", "  ▼"]
        # Fan-out: show branches
        lines: list[str] = []
        for i, edge in enumerate(edges):
            connector = "└" if i == len(edges) - 1 else "├"
            cond = ""
            if edge.condition.value not in ("always", "on_success"):
                cond = f" [dim]({edge.condition.value})[/dim]"
            lines.append(f"  {connector}──▶ {edge.target}{cond}")
        return lines

    def _display_graph(self) -> None:
        """Display the graph as an ASCII DAG with edge connectors."""
        display = self.query_one("#graph-display", RichLog)
        display.clear()

        graph = self.runtime.graph
        display.write(f"[bold cyan]Agent Graph:[/bold cyan] {graph.id}\n")

        # Render each node in topological order with edges
        ordered = self._topo_order()
        for node_id in ordered:
            display.write(self._render_node_line(node_id))
            for edge_line in self._render_edges(node_id):
                display.write(edge_line)

        # Execution path footer
        if self.execution_path:
            display.write("")
            display.write(f"[dim]Path:[/dim] {' → '.join(self.execution_path[-5:])}")

    def update_active_node(self, node_id: str) -> None:
        """Update the currently active node."""
        self.active_node = node_id
        if node_id not in self.execution_path:
            self.execution_path.append(node_id)
        self._display_graph()

    def update_execution(self, event) -> None:
        """Update the displayed node status based on execution lifecycle events."""
        if event.type == EventType.EXECUTION_STARTED:
            self._node_status.clear()
            self.execution_path.clear()
            entry_node = event.data.get("entry_node") or (
                self.runtime.graph.entry_node if self.runtime else None
            )
            if entry_node:
                self.update_active_node(entry_node)

        elif event.type == EventType.EXECUTION_COMPLETED:
            self.active_node = None
            self._node_status.clear()
            self._display_graph()

        elif event.type == EventType.EXECUTION_FAILED:
            error = event.data.get("error", "Unknown error")
            if self.active_node:
                self._node_status[self.active_node] = f"[red]FAILED: {error}[/red]"
            self.active_node = None
            self._display_graph()

    # -- Event handlers called by app.py _handle_event --

    def handle_node_loop_started(self, node_id: str) -> None:
        """A node's event loop has started."""
        self._node_status[node_id] = "thinking..."
        self.update_active_node(node_id)

    def handle_node_loop_iteration(self, node_id: str, iteration: int) -> None:
        """A node advanced to a new loop iteration."""
        self._node_status[node_id] = f"step {iteration}"
        self._display_graph()

    def handle_node_loop_completed(self, node_id: str) -> None:
        """A node's event loop completed."""
        self._node_status.pop(node_id, None)
        self._display_graph()

    def handle_tool_call(self, node_id: str, tool_name: str, *, started: bool) -> None:
        """Show tool activity next to the active node."""
        if started:
            self._node_status[node_id] = f"{tool_name}..."
        else:
            # Restore to generic thinking status after tool completes
            self._node_status[node_id] = "thinking..."
        self._display_graph()

    def handle_stalled(self, node_id: str, reason: str) -> None:
        """Highlight a stalled node."""
        self._node_status[node_id] = f"[red]stalled: {reason}[/red]"
        self._display_graph()
