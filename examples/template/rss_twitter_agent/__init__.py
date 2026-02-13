"""
RSS-to-Twitter Agent - Automated content repurposing from RSS feeds to Twitter threads.

Fetches articles from configured RSS feeds, extracts key points,
and generates engaging Twitter threads for user review.
"""

from .agent import RSSTwitterAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "RSSTwitterAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
