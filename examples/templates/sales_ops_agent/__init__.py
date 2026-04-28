"""
Sales Ops Agent — Automated sales territory rebalancing.

Runs monthly on the 1st to analyze sales performance, detect under-allocated
territories, and rebalance accounts from unassigned pools to ensure fair
opportunity distribution.
"""

from .agent import (
    SalesOpsAgent,
    conversation_mode,
    default_agent,
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
from .config import AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "SalesOpsAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "loop_config",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "AgentMetadata",
    "default_config",
    "metadata",
]
