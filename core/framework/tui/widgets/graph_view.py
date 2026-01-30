"""
Graph/Tree Overview Widget.
"""

from textual.widgets import Tree, Static

class GraphOverview(Static):
    """Widget to display Agent execution graph/tree."""
    
    def compose(self):
        self._execution_tree = Tree("Active Node: Initializing...")
        self._execution_tree.root.expand()
        yield self._execution_tree

    def update_execution(self, event) -> None:
        """Update the displayed node status based on event."""
        # This is a simplified visualization
        if event.type.value == "execution_started":
            # Add node to tree or update current
            stream_id = event.stream_id
            data = event.data
            
            # For now just add a child to root
            self._execution_tree.root.add(f"[{event.timestamp.strftime('%H:%M:%S')}] Started: {stream_id}", expand=True)
            
        elif event.type.value == "execution_completed":
             self._execution_tree.root.add(f"[green]Completed: {event.stream_id}[/green]")
        elif event.type.value == "execution_failed":
             self._execution_tree.root.add(f"[red]Failed: {event.stream_id} - {event.data.get('error')}[/red]")
