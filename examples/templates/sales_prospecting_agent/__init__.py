"""B2B Sales Prospecting & Outreach Agent Template."""

from .agent import (
    SalesProspectingAgent,
    default_agent,
    goal,
    nodes,
    edges,
    entry_node,
    entry_points,
    terminal_nodes,
    pause_nodes,
)
from .config import default_config, metadata

__all__ = [
    "SalesProspectingAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "terminal_nodes",
    "pause_nodes",
    "default_config",
    "metadata",
]
