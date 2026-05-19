"""
Queen — Native agent builder for the Hive framework.

Deeply understands the agent framework and produces complete Python packages
with goals, nodes, edges, system prompts, MCP configuration, and tests
from natural language specifications.
"""

from .agent import queen_goal, queen_graph
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "queen_goal",
    "queen_graph",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
