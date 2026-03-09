"""
GTM Signal Intelligence Agent - End-to-end signal monitoring, enrichment, and outreach.

Continuously detects GTM signals, enriches leads, scores opportunities,
drafts outreach, and supports human approval before CRM actions.
"""

from .agent import GTMSignalAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "GTMSignalAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
