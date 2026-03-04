"""
Vercel Assistant Agent - Interactive deployment management.

Help users manage Vercel deployments, projects, and environment variables
through natural language interaction with clear guidance and feedback.
"""

from .agent import VercelAssistant, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "VercelAssistant",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
