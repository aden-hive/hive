"""
Hive Coder — Native coding agent that builds Hive agent packages.

Deeply understands the agent framework and produces complete Python packages
with goals, nodes, edges, system prompts, MCP configuration, and tests
from natural language specifications.
"""

from .agent import (
    conversation_mode,
    edges,
    entry_node,
    entry_points,
    goal,
    identity_prompt,
    loop_config,
    nodes,
    pause_nodes,
    terminal_nodes,
)
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "loop_config",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
