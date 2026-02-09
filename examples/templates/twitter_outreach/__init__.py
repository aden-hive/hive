"""
Twitter Outreach Agent - Personalized email outreach powered by Twitter/X research.

Reads a target's Twitter/X profile, crafts a personalized outreach email
referencing their specific activity, and sends it after user approval.
"""

from .agent import TwitterOutreachAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "TwitterOutreachAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
