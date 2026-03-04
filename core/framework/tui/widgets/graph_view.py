"""
Graph/Tree Overview Widget - Displays real agent graph structure.

Supports rendering loops (back-edges) via right-side return channels:
arrows drawn on the right margin that visually point back up to earlier nodes.
"""

from __future__ import annotations

import re
import time

from textual.app import ComposeResult
from textual.containers import Vertical

from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import EventType
from framework.tui.widgets.selectable_rich_log import SelectableRichLog as RichLog

# Width of each return-channel column (padding + │ + gap)
_CHANNEL_WIDTH = 5

# Regex to strip Rich markup tags for measuring visible width
_MARKUP_RE = re.compile(r"\[/?[^\]]*\]")


def _plain_len(s: str) -> int:
    """Return the visible character length of a Rich-markup string."""
    return len(_MARKUP_RE.sub("", s))


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
        self._override_graph = None  # Set by switch_graph() for secondary graphs
        self.active_node: str | None = None
        self.execution_path: list[str] = []
        # Per-node status strings shown next to the node in the graph display.
        # e.g. {"planner": "thinking...", "searcher": "web_search..."}
        self._node_status: dict[str, str] = {}

    @property
    def _graph(self):
        """The graph currently being displayed (may be a secondary graph)."""
        return self._override_graph or self.runtime.graph

    def switch_graph(self, graph) -> None:
        """Switch to displaying a different graph and refresh."""
        self._override_graph = graph
        self.active_node = None
        self.execution_path = []
        self._node_status = {}
        self._display_graph()

    def compose(self) -> ComposeResult:
        # Use RichLog for formatted output
        yield RichLog(id="graph-display", highlight=True, markup=True)

    def on_mount(self) -> None:
        """Display initial graph structure."""
        self._display_graph()
        # Refresh every 1s so timer countdowns stay current
        if self.runtime._timer_next_fire is not None:
            self.set_interval(1.0, self._display_graph)

    # ------------------------------------------------------------------
    # Graph analysis helpers
    # ------------------------------------------------------------------

    def _topo_order(self) -> list[str]:
        """BFS from entry_node following edges."""
        graph = self._graph
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

    def _detect_back_edges(self, ordered: list[str]) -> list[dict]:
        """Find edges where target appears before (or equal to) source in topo order.

        Returns a list of dicts with keys: edge, source, target, source_idx, target_idx.
        """
        order_idx = {nid: i for i, nid in enumerate(ordered)}
        back_edges: list[dict] = []
        for node_id in ordered:
            for edge in self._graph.get_outgoing_edges(node_id):
                target_idx = order_idx.get(edge.target, -1)
                source_idx = order_idx.get(node_id, -1)
                if target_idx != -1 and target_idx <= source_idx:
                    back_edges.append(
                        {
                            "edge": edge,
                            "source": node_id,
                            "target": edge.target,
                            "source_idx": source_idx,
                            "target_idx": target_idx,
                        }
                    )
        return back_edges

    def _is_back_edge(self, source: str, target: str, order_idx: dict[str, int]) -> bool:
        """Check whether an edge from *source* to *target* is a back-edge."""
        si = order_idx.get(source, -1)
        ti = order_idx.get(target, -1)
        return ti != -1 and ti <= si

    # ------------------------------------------------------------------
    # Line rendering (Pass 1)
    # ------------------------------------------------------------------

    def _render_node_line(self, node_id: str) -> str:
        """Render a single node with status symbol and optional status text."""
        graph = self._graph
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

    def _render_edges(self, node_id: str, order_idx: dict[str, int]) -> list[str]:
        """Render forward-edge connectors from *node_id*.

        Back-edges are excluded here — they are drawn by the return-channel
        overlay in Pass 2.
        """
        all_edges = self._graph.get_outgoing_edges(node_id)
        if not all_edges:
            return []

        # Split into forward and back
        forward = [e for e in all_edges if not self._is_back_edge(node_id, e.target, order_idx)]

        if not forward:
            # All edges are back-edges — nothing to render here
            return []

        if len(forward) == 1:
            return ["  │", "  ▼"]

        # Fan-out: show branches
        lines: list[str] = []
        for i, edge in enumerate(forward):
            connector = "└" if i == len(forward) - 1 else "├"
            cond = ""
            if edge.condition.value not in ("always", "on_success"):
                cond = f" [dim]({edge.condition.value})[/dim]"
            lines.append(f"  {connector}──▶ {edge.target}{cond}")
        return lines

    # ------------------------------------------------------------------
    # Return-channel overlay (Pass 2)
    # ------------------------------------------------------------------

    def _overlay_return_channels(
        self,
        lines: list[str],
        node_line_map: dict[str, int],
        back_edges: list[dict],
        available_width: int,
    ) -> list[str]:
        """Overlay right-side return channels onto the line buffer.

        Each back-edge gets a vertical channel on the right margin.  Channels
        are allocated left-to-right by increasing span length so that shorter
        (inner) loops are closer to the graph body and longer (outer) loops are
        further right.

        If the terminal is too narrow to fit even one channel, we fall back to
        simple inline ``↺`` annotations instead.
        """
        if not back_edges:
            return lines

        num_channels = len(back_edges)

        # Sort by span length ascending → inner loops get nearest channel
        sorted_be = sorted(back_edges, key=lambda b: b["source_idx"] - b["target_idx"])

        # --- Insert dedicated connector lines for back-edge sources ---
        # Each back-edge source gets a blank line inserted after its node
        # section (after any forward-edge lines).  We process insertions in
        # reverse order so that earlier indices remain valid.
        all_node_lines_set = set(node_line_map.values())

        insertions: list[tuple[int, int]] = []  # (insert_after_line, be_index)
        for be_idx, be in enumerate(sorted_be):
            source_node_line = node_line_map.get(be["source"])
            if source_node_line is None:
                continue
            # Walk forward to find the last line in this node's section
            last_section_line = source_node_line
            for li in range(source_node_line + 1, len(lines)):
                if li in all_node_lines_set:
                    break
                last_section_line = li
            insertions.append((last_section_line, be_idx))

        source_line_for_be: dict[int, int] = {}
        for insert_after, be_idx in sorted(insertions, reverse=True):
            insert_at = insert_after + 1
            lines.insert(insert_at, "")  # placeholder for connector
            source_line_for_be[be_idx] = insert_at
            # Shift node_line_map entries that come after the insertion point
            for nid in node_line_map:
                if node_line_map[nid] > insert_after:
                    node_line_map[nid] += 1
            # Also shift already-assigned source lines
            for prev_idx in source_line_for_be:
                if prev_idx != be_idx and source_line_for_be[prev_idx] > insert_after:
                    source_line_for_be[prev_idx] += 1

        # Recompute max content width after insertions
        max_content_w = max(_plain_len(ln) for ln in lines) if lines else 0

        # Check if we have room for channels
        channels_total_w = num_channels * _CHANNEL_WIDTH
        if max_content_w + channels_total_w + 2 > available_width:
            return self._inline_back_edge_fallback(lines, node_line_map, back_edges)

        content_pad = max_content_w + 3  # gap between content and first channel

        # Build channel info with final line positions
        channel_info: list[dict] = []
        for ch_idx, be in enumerate(sorted_be):
            target_line = node_line_map.get(be["target"])
            source_line = source_line_for_be.get(ch_idx)
            if target_line is None or source_line is None:
                continue
            col = content_pad + ch_idx * _CHANNEL_WIDTH
            channel_info.append(
                {
                    "target_line": target_line,
                    "source_line": source_line,
                    "col": col,
                }
            )

        if not channel_info:
            return lines

        # Build overlay grid — one row per line, columns for channel area
        total_width = content_pad + num_channels * _CHANNEL_WIDTH + 1
        overlay_width = total_width - max_content_w
        overlays: list[list[str]] = [[" "] * overlay_width for _ in range(len(lines))]

        for ci in channel_info:
            tl = ci["target_line"]
            sl = ci["source_line"]
            col_offset = ci["col"] - max_content_w

            if col_offset < 0 or col_offset >= overlay_width:
                continue

            # Target line: ◄──...──┐
            if 0 <= tl < len(overlays):
                for c in range(col_offset):
                    if overlays[tl][c] == " ":
                        overlays[tl][c] = "─"
                overlays[tl][col_offset] = "┐"

            # Source line: ──...──┘
            if 0 <= sl < len(overlays):
                for c in range(col_offset):
                    if overlays[sl][c] == " ":
                        overlays[sl][c] = "─"
                overlays[sl][col_offset] = "┘"

            # Vertical lines between target+1 and source-1
            for li in range(tl + 1, sl):
                if 0 <= li < len(overlays) and overlays[li][col_offset] == " ":
                    overlays[li][col_offset] = "│"

        # Merge overlays into the line strings
        result: list[str] = []
        for i, line in enumerate(lines):
            pw = _plain_len(line)
            pad = max_content_w - pw
            overlay_chars = overlays[i] if i < len(overlays) else []
            overlay_str = "".join(overlay_chars)
            overlay_trimmed = overlay_str.rstrip()
            if overlay_trimmed:
                is_target_line = any(ci["target_line"] == i for ci in channel_info)
                if is_target_line:
                    overlay_trimmed = "◄" + overlay_trimmed[1:]

                is_source_line = any(ci["source_line"] == i for ci in channel_info)
                if is_source_line and not line.strip():
                    # Inserted blank line → build └───┘ connector.
                    # "  └" = 3 chars of content prefix, so remaining pad = max_content_w - 3
                    remaining_pad = max_content_w - 3
                    full = list(" " * remaining_pad + overlay_trimmed)
                    # Find the ┘ corner for this source connector
                    corner_pos = -1
                    for ci_s in channel_info:
                        if ci_s["source_line"] == i:
                            corner_pos = remaining_pad + (ci_s["col"] - max_content_w)
                            break
                    # Fill everything up to the corner with ─
                    if corner_pos >= 0:
                        for c in range(corner_pos):
                            if full[c] not in ("│", "┘", "┐"):
                                full[c] = "─"
                    connector = "  └" + "".join(full).rstrip()
                    result.append(f"[dim]{connector}[/dim]")
                    continue

                colored_overlay = f"[dim]{' ' * pad}{overlay_trimmed}[/dim]"
                result.append(f"{line}{colored_overlay}")
            else:
                result.append(line)

        return result

    def _inline_back_edge_fallback(
        self,
        lines: list[str],
        node_line_map: dict[str, int],
        back_edges: list[dict],
    ) -> list[str]:
        """Fallback: add inline ↺ annotations when terminal is too narrow for channels."""
        # Group back-edges by source node
        source_to_be: dict[str, list[dict]] = {}
        for be in back_edges:
            source_to_be.setdefault(be["source"], []).append(be)

        result = list(lines)
        # Insert annotation lines after each source node's section
        offset = 0
        all_node_lines = sorted(node_line_map.values())
        for source, bes in source_to_be.items():
            source_line = node_line_map.get(source)
            if source_line is None:
                continue
            # Find end of source node section
            end_line = source_line
            for nl in all_node_lines:
                if nl > source_line:
                    end_line = nl - 1
                    break
            else:
                end_line = len(lines) - 1
            # Insert after last content line of this node's section
            insert_at = end_line + offset + 1
            for be in bes:
                cond = ""
                edge = be["edge"]
                if edge.condition.value not in ("always", "on_success"):
                    cond = f" [dim]({edge.condition.value})[/dim]"
                annotation = f"  [yellow]↺[/yellow] {be['target']}{cond}"
                result.insert(insert_at, annotation)
                insert_at += 1
                offset += 1

        return result

    # ------------------------------------------------------------------
    # Main display
    # ------------------------------------------------------------------

    def _display_graph(self) -> None:
        """Display the graph as an ASCII DAG with edge connectors and loop channels."""
        display = self.query_one("#graph-display", RichLog)
        display.clear()

        graph = self._graph
        display.write(f"[bold cyan]Agent Graph:[/bold cyan] {graph.id}\n")

        ordered = self._topo_order()
        order_idx = {nid: i for i, nid in enumerate(ordered)}

        # --- Pass 1: Build line buffer ---
        lines: list[str] = []
        node_line_map: dict[str, int] = {}

        for node_id in ordered:
            node_line_map[node_id] = len(lines)
            lines.append(self._render_node_line(node_id))
            for edge_line in self._render_edges(node_id, order_idx):
                lines.append(edge_line)

        # --- Pass 2: Overlay return channels for back-edges ---
        back_edges = self._detect_back_edges(ordered)
        if back_edges:
            # Try to get actual widget width; default to a reasonable value
            try:
                available_width = self.size.width or 60
            except Exception:
                available_width = 60
            lines = self._overlay_return_channels(lines, node_line_map, back_edges, available_width)

        # Write all lines
        for line in lines:
            display.write(line)

        # Execution path footer
        if self.execution_path:
            display.write("")
            display.write(f"[dim]Path:[/dim] {' → '.join(self.execution_path[-5:])}")

        # Event sources section
        self._render_event_sources(display)

    # ------------------------------------------------------------------
    # Event sources display
    # ------------------------------------------------------------------

    def _render_event_sources(self, display: RichLog) -> None:
        """Render event source info (webhooks, timers) below the graph."""
        entry_points = self.runtime.get_entry_points()

        # Filter to non-manual entry points (webhooks, timers, events)
        event_sources = [ep for ep in entry_points if ep.trigger_type not in ("manual",)]
        if not event_sources:
            return

        display.write("")
        display.write("[bold cyan]Event Sources[/bold cyan]")

        config = self.runtime._config

        for ep in event_sources:
            if ep.trigger_type == "timer":
                cron_expr = ep.trigger_config.get("cron")
                interval = ep.trigger_config.get("interval_minutes", "?")
                schedule_label = f"cron: {cron_expr}" if cron_expr else f"every {interval} min"
                display.write(f"  [green]⏱[/green]  {ep.name} [dim]→ {ep.entry_node}[/dim]")
                # Show schedule + next fire countdown
                next_fire = self.runtime._timer_next_fire.get(ep.id)
                if next_fire is not None:
                    remaining = max(0, next_fire - time.monotonic())
                    hours, rem = divmod(int(remaining), 3600)
                    mins, secs = divmod(rem, 60)
                    if hours > 0:
                        countdown = f"{hours}h {mins:02d}m {secs:02d}s"
                    else:
                        countdown = f"{mins}m {secs:02d}s"
                    display.write(f"     [dim]{schedule_label} — next in {countdown}[/dim]")
                else:
                    display.write(f"     [dim]{schedule_label}[/dim]")

            elif ep.trigger_type in ("event", "webhook"):
                display.write(f"  [yellow]⚡[/yellow] {ep.name} [dim]→ {ep.entry_node}[/dim]")
                # Show webhook endpoint if configured
                route = None
                for r in config.webhook_routes:
                    src = r.get("source_id", "")
                    if src and src in ep.id:
                        route = r
                        break
                if not route and config.webhook_routes:
                    # Fall back to first route
                    route = config.webhook_routes[0]

                if route:
                    host = config.webhook_host
                    port = config.webhook_port
                    path = route.get("path", "/webhook")
                    display.write(f"     [dim]{host}:{port}{path}[/dim]")
                else:
                    event_types = ep.trigger_config.get("event_types", [])
                    if event_types:
                        display.write(f"     [dim]events: {', '.join(event_types)}[/dim]")

    # ------------------------------------------------------------------
    # Public API (called by app.py)
    # ------------------------------------------------------------------

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
                self._graph.entry_node if self.runtime else None
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
        if self.active_node == node_id:
            self.active_node = None
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

    def handle_edge_traversed(self, source_node: str, target_node: str) -> None:
        """Highlight an edge being traversed."""
        self._node_status[source_node] = f"[dim]→ {target_node}[/dim]"
        self._display_graph()
