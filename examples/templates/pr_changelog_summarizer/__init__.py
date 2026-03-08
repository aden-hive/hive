"""
PR Changelog Summarizer - Summarize GitHub PRs into changelog documents.

Fetches recent pull requests from a repository and generates a formatted
changelog or release notes document.
"""

from .agent import (
    PRChangelogSummarizerAgent,
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
    "PRChangelogSummarizerAgent",
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
