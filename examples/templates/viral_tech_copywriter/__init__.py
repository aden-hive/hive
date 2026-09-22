"""
Viral Tech Copywriter — conversational brief to multi-channel tech marketing copy.

Flow: intake → normalize-brief → write-package → deliver-exports (HTML/Markdown via hive-tools MCP).
"""

from __future__ import annotations

from .agent import (
    ViralTechCopywriterAgent,
    default_agent,
    edges,
    entry_node,
    entry_points,
    goal,
    nodes,
    pause_nodes,
    skip_credential_validation,
    terminal_nodes,
)
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "ViralTechCopywriterAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "skip_credential_validation",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
