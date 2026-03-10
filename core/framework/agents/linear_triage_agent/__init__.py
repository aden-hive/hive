"""Linear Triage & Auto-Labeling Agent — Router Pattern implementation.

Autonomous triage agent that:
- Ingests raw issue descriptions
- Classifies them (Bug, Feature, Security)
- Determines priority (P0-P3)
- Uses Router Pattern with Conditional Edges to dispatch to specialized nodes
- Generates simulated Linear API payload
"""

from .agent import (
    LinearTriageAgent,
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
from .config import default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "LinearTriageAgent",
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
]
