"""
Graph/Tree Overview Widget.
"""

from textual.widgets import Tree, Static

class GraphOverview(Static):
    """Widget to display Agent execution graph/tree."""
    
    def compose(self):
        self.tree = Tree("Active Node: Initializing...")
        self.tree.root.expand()
        yield self.tree

    def update_execution(self, event) -> None:
        """Update the displayed node status based on event."""
        # This is a simplified visualization
        if event.type.value == "execution_started":
            # Add node to tree or update current
            stream_id = event.stream_id
            data = event.data
            
            # For now just add a child to root
            self.tree.root.add(f"[{event.timestamp.strftime('%H:%M:%S')}] Started: {stream_id}", expand=True)
            
        elif event.type.value == "execution_completed":
             self.tree.root.add(f"[green]Completed: {event.stream_id}[/green]")
        elif event.type.value == "execution_failed":
             self.tree.root.add(f"[red]Failed: {event.stream_id} - {event.data.get('error')}[/red]")
