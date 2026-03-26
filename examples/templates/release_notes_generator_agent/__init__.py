"""
Release Notes Generator Agent
Automatically generate structured release notes from changes.
"""

from .agent import (
    goal,
    nodes,
    edges,
    entry_node,
    entry_points,
    pause_nodes,
    terminal_nodes,
)

__all__ = [
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
]
