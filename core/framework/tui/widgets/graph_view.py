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
        # Diff mode state
        self._diff_mode: bool = False
        self._last_old_graph: dict | None = None
        self._last_new_graph: dict | None = None
        # Selected node index for diff-mode navigation
        self._selected_index: int | None = None

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

        if self._diff_mode and self._last_new_graph is not None:
            return self._display_graph_diff()

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

    def _serialize_graph(self, graph_obj: object | dict) -> dict:
        """Normalize graph object or dict into a plain dict with nodes and edges.

        Accepts GraphSpec instances or already-serialized dicts.
        """
        if graph_obj is None:
            return {"nodes": [], "edges": [], "id": ""}
        if isinstance(graph_obj, dict):
            return graph_obj
        # Try to convert pydantic model to dict
        try:
            return graph_obj.model_dump()  # Pydantic v2 method
        except Exception:
            try:
                return graph_obj.dict()
            except Exception:
                return {"nodes": [], "edges": [], "id": getattr(graph_obj, "id", "")}

    def _display_graph_diff(self) -> None:
        """Render a visual diff between last_old_graph and last_new_graph.

        Color and symbol legend:
          [green]+  new node/edge
          [red]-    removed node/edge
          [yellow]~ modified node
        """
        display = self.query_one("#graph-display", RichLog)
        display.clear()

        old = self._serialize_graph(self._last_old_graph)
        new = self._serialize_graph(self._last_new_graph)

        old_nodes = {
            (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n))): n
            for n in old.get("nodes", [])
        }
        new_nodes = {
            (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n))): n
            for n in new.get("nodes", [])
        }

        old_edges = set()
        for e in old.get("edges", []):
            src = e.get("source") if isinstance(e, dict) else getattr(e, "source", None)
            tgt = e.get("target") if isinstance(e, dict) else getattr(e, "target", None)
            cond = e.get("condition", "") if isinstance(e, dict) else getattr(e, "condition", "")
            old_edges.add(f"{src}->{tgt}:{cond}")

        new_edges = set()
        for e in new.get("edges", []):
            src = e.get("source") if isinstance(e, dict) else getattr(e, "source", None)
            tgt = e.get("target") if isinstance(e, dict) else getattr(e, "target", None)
            cond = e.get("condition", "") if isinstance(e, dict) else getattr(e, "condition", "")
            new_edges.add(f"{src}->{tgt}:{cond}")

        added_nodes = set(new_nodes.keys()) - set(old_nodes.keys())
        removed_nodes = set(old_nodes.keys()) - set(new_nodes.keys())
        modified_nodes = set()
        for nid in set(new_nodes.keys()).intersection(old_nodes.keys()):
            # Simple deep-compare of node dicts
            old_n = old_nodes[nid]
            new_n = new_nodes[nid]
            try:
                if isinstance(old_n, dict) and isinstance(new_n, dict):
                    if old_n != new_n:
                        modified_nodes.add(nid)
                else:
                    if str(old_n) != str(new_n):
                        modified_nodes.add(nid)
            except Exception:
                continue

        display.write(
            f"[bold cyan]Graph Diff:[/bold cyan] "
            f"{new.get('id') or getattr(self.runtime.graph, 'id', '')}\n"
        )

        # Render each node in new graph order (fall back to runtime graph)
        ordered = []
        if new.get("nodes"):
            ordered = [
                (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n)))
                for n in new.get("nodes")
            ]
        else:
            ordered = self._topo_order()

        # Render nodes; keep an index for selection navigation
        for idx, node_id in enumerate(ordered):
            if node_id in added_nodes:
                display.write(f"  [green]+ {node_id}[/green]")
            elif node_id in modified_nodes:
                sel_marker = ""
                if self._selected_index is not None and idx == self._selected_index:
                    sel_marker = " [bold]<selected>[/bold]"
                display.write(f"  [yellow]~ {node_id}[/yellow]{sel_marker}")
                # If this modified node is selected, show per-field diffs
                if self._selected_index is not None and idx == self._selected_index:
                    old_n = old_nodes.get(node_id) or {}
                    new_n = new_nodes.get(node_id) or {}
                    for line in self._node_property_diffs(old_n, new_n):
                        display.write(f"    {line}")
            else:
                display.write(self._render_node_line(node_id))

            # Show outgoing edges with markers for added/removed
            # Use edges from new graph when available
            edges = []
            for e in new.get("edges", []):
                src = e.get("source") if isinstance(e, dict) else getattr(e, "source", None)
                if src == node_id:
                    tgt = e.get("target") if isinstance(e, dict) else getattr(e, "target", None)
                    cond = (
                        e.get("condition", "")
                        if isinstance(e, dict)
                        else getattr(e, "condition", "")
                    )
                    key = f"{src}->{tgt}:{cond}"
                    if key in new_edges - old_edges:
                        connector = f"[green]+──▶ {tgt}[/green]"
                    else:
                        connector = f"──▶ {tgt}"
                    edges.append(f"  {connector}")

            # Also show removed edges originating from this node
            for e in old.get("edges", []):
                src = e.get("source") if isinstance(e, dict) else getattr(e, "source", None)
                if src == node_id:
                    tgt = e.get("target") if isinstance(e, dict) else getattr(e, "target", None)
                    cond = (
                        e.get("condition", "")
                        if isinstance(e, dict)
                        else getattr(e, "condition", "")
                    )
                    key = f"{src}->{tgt}:{cond}"
                    if key in old_edges - new_edges:
                        edges.append(f"  [red]-──▶ {tgt}[/red]")

            for line in edges:
                display.write(line)

        # Footer with summary
        display.write("")
        summary = []
        if added_nodes:
            summary.append(f"[green]+{len(added_nodes)} new[/green]")
        if removed_nodes:
            summary.append(f"[red]-{len(removed_nodes)} removed[/red]")
        if modified_nodes:
            summary.append(f"[yellow]~{len(modified_nodes)} modified[/yellow]")
        if summary:
            display.write("Summary: " + " • ".join(summary))

    def _node_property_diffs(self, old_n: dict, new_n: dict) -> list[str]:
        """Return a list of formatted property-diff strings for a modified node.

        Format: key: [red]old[/red] -> [green]new[/green]
        """
        lines: list[str] = []
        # Normalize to dicts
        if not isinstance(old_n, dict):
            try:
                old_n = old_n.model_dump()
            except Exception:
                old_n = {}
        if not isinstance(new_n, dict):
            try:
                new_n = new_n.model_dump()
            except Exception:
                new_n = {}

        # Keys to consider (union)
        keys = sorted(set(list(old_n.keys()) + list(new_n.keys())))
        for k in keys:
            ov = old_n.get(k)
            nv = new_n.get(k)
            if ov == nv:
                continue
            # Shorten large values
            def short(x):
                s = str(x)
                if len(s) > 60:
                    return s[:57] + "..."
                return s

            lines.append(f"[dim]{k}:[/dim] [red]{short(ov)}[/red] -> [green]{short(nv)}[/green]")
        if not lines:
            lines.append("[dim]No property-level differences found[/dim]")
        return lines

    def on_key(self, event) -> None:
        """Handle up/down keys for diff-mode selection navigation."""
        try:
            if not self._diff_mode:
                return
            # Recompute modified nodes and only navigate among them
            new = self._serialize_graph(self._last_new_graph or {})
            old = self._serialize_graph(self._last_old_graph or {})

            ordered = [
                (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n)))
                for n in new.get("nodes", [])
            ]

            # compute modified set (same logic as in _display_graph_diff)
            old_nodes = {
                (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n))): n
                for n in old.get("nodes", [])
            }
            new_nodes = {
                (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n))): n
                for n in new.get("nodes", [])
            }

            modified = []
            for nid in [n for n in ordered if n in old_nodes or n in new_nodes]:
                if nid in old_nodes and nid in new_nodes:
                    try:
                        if old_nodes[nid] != new_nodes[nid]:
                            modified.append(nid)
                    except Exception:
                        if str(old_nodes[nid]) != str(new_nodes[nid]):
                            modified.append(nid)
                elif nid in old_nodes or nid in new_nodes:
                    # added or removed counts as modified for navigation
                    modified.append(nid)

            if not modified:
                return

            # initialize selection to first modified if none
            if self._selected_index is None or self._selected_index >= len(modified):
                # store selected as index in `modified` list
                self._selected_index = 0

            if event.key == "up":
                self._selected_index = max(0, self._selected_index - 1)
                # map selected_index back to ordered index by finding that node's position
                self._display_graph_diff()
            elif event.key == "down":
                self._selected_index = min(len(modified) - 1, self._selected_index + 1)
                self._display_graph_diff()
            elif event.key == "enter":
                # Show full diff for currently selected modified node
                try:
                    # Map to node id
                    node_id = modified[self._selected_index]
                except Exception:
                    node_id = modified[0]
                self.show_full_diff(node_id)
        except Exception:
            pass

    def show_full_diff(self, node_id: str | None = None) -> None:
        """Show a focused, detailed diff for a node.

        If node_id is None, use the selected node. This writes a detailed
        block to the widget's display containing the old/new JSON and
        the per-field diffs produced by `_node_property_diffs`.
        """
        display = self.query_one("#graph-display", RichLog)
        try:
            old = self._serialize_graph(self._last_old_graph or {})
            new = self._serialize_graph(self._last_new_graph or {})

            old_nodes = {
                (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n))): n
                for n in old.get("nodes", [])
            }
            new_nodes = {
                (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n))): n
                for n in new.get("nodes", [])
            }

            # Determine node id
            nid = node_id
            if nid is None:
                # pick selected modified node if possible
                if self._selected_index is not None:
                    ordered = [
                        (n["id"] if isinstance(n, dict) else getattr(n, "id", str(n)))
                        for n in new.get("nodes", [])
                    ]
                    # Recompute modified list
                    modified = [
                        x for x in ordered
                        if (x in old_nodes and x in new_nodes and old_nodes[x] != new_nodes[x])
                        or (x in old_nodes and x not in new_nodes)
                        or (x not in old_nodes and x in new_nodes)
                    ]
                    if modified:
                        nid = modified[self._selected_index % len(modified)]
            if nid is None:
                display.write("[dim]No node selected for full diff[/dim]")
                return

            old_node = old_nodes.get(nid)
            new_node = new_nodes.get(nid)

            import json

            display.clear()
            display.write(f"[bold cyan]Full diff for node:[/bold cyan] {nid}\n")
            display.write("[bold]Per-field differences:[/bold]\n")
            for line in self._node_property_diffs(old_node or {}, new_node or {}):
                display.write(line)

            display.write("")
            display.write("[bold]Old node (raw):[/bold]\n")
            try:
                display.write(f"[dim]{json.dumps(old_node or {}, indent=2)}[/dim]")
            except Exception:
                display.write(f"[dim]{str(old_node)}[/dim]")

            display.write("")
            display.write("[bold]New node (raw):[/bold]\n")
            try:
                display.write(f"[dim]{json.dumps(new_node or {}, indent=2)}[/dim]")
            except Exception:
                display.write(f"[dim]{str(new_node)}[/dim]")
        except Exception:
            pass

    def handle_graph_evolved(self, old_graph: dict | None, new_graph: dict | None) -> None:
        """Called when the runtime emits a GRAPH_EVOLVED event.

        Store snapshots and enter diff mode so the user can inspect changes.
        """
        self._last_old_graph = old_graph or {}
        self._last_new_graph = new_graph or {}
        # Enter diff mode automatically
        self._diff_mode = True
        self._display_graph_diff()

    def toggle_diff_mode(self) -> None:
        """Toggle between live view and diff view."""
        self._diff_mode = not self._diff_mode
        if self._diff_mode:
            # If diff requested but we don't have snapshots, fall back to showing current graph
            if self._last_new_graph is None:
                self._last_new_graph = getattr(self.runtime, "graph", None)
            self._display_graph_diff()
        else:
            self._display_graph()

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
