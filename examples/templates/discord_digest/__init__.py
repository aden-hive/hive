"""
Discord Community Digest - Monitor Discord servers and deliver actionable summaries.

Scans Discord servers, categorizes messages by priority, and delivers
a digest as a Discord DM so you know what needs your attention.
"""

from .agent import DiscordDigestAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "DiscordDigestAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
