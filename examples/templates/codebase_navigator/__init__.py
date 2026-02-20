"""
Codebase Navigator - Navigate unfamiliar codebases with file tools only.

Uses list_dir, grep_search, view_file from hive-tools. No third-party credentials.
Flow: intake -> explore -> search -> synthesize -> deliver
"""

from __future__ import annotations

from .agent import (
    CodebaseNavigatorAgent,
    default_agent,
    edges,
    entry_node,
    entry_points,
    goal,
    nodes,
    pause_nodes,
    terminal_nodes,
)
from .config import AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "CodebaseNavigatorAgent",
    "default_agent",
    "edges",
    "entry_node",
    "entry_points",
    "goal",
    "nodes",
    "pause_nodes",
    "terminal_nodes",
    "AgentMetadata",
    "default_config",
    "metadata",
]
