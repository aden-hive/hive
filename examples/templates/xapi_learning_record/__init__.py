"""xAPI Learning Record Agent — deterministic LRS sidecar for Hive templates.

Captures learning events, builds valid xAPI 1.0.3 statements, validates
structure, dispatches to an LRS via HTTP Basic auth, and returns confirmation.
No LLM required for statement building, validation, or dispatch.
"""

__version__ = "0.1.0"

from .agent import (
    XAPILearningRecordAgent,
    default_agent,
    goal,
    nodes,
    edges,
    entry_node,
    entry_points,
    pause_nodes,
    terminal_nodes,
    loop_config,
    conversation_mode,
    identity_prompt,
)
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__all__ = [
    "XAPILearningRecordAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "loop_config",
    "conversation_mode",
    "identity_prompt",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
