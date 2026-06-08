"""
SDR Agent — Automated sales development outreach pipeline.

Score contacts by priority, filter suspicious profiles, generate personalized
outreach messages, and create Gmail drafts for human review before sending.
"""

from .agent import (
    SDRAgent,
    default_agent,
    goal,
    nodes,
    edges,
    loop_config,
    async_entry_points,
    entry_node,
    entry_points,
    pause_nodes,
    terminal_nodes,
    conversation_mode,
    identity_prompt,
)
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "SDRAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "loop_config",
    "async_entry_points",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
