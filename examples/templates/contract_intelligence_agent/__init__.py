"""Contract Intelligence & Risk Agent — Automated Contract Review and Clause Risk Scoring."""

from .agent import (
    ContractIntelligenceAgent,
    default_agent,
    goal,
    nodes,
    edges,
    entry_node,
    entry_points,
    pause_nodes,
    terminal_nodes,
    conversation_mode,
    identity_prompt,
    loop_config,
)
from .config import default_config, metadata, DEFAULT_BASELINE_TEMPLATE

__all__ = [
    "ContractIntelligenceAgent",
    "default_agent",
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
    "default_config",
    "metadata",
    "DEFAULT_BASELINE_TEMPLATE",
]
