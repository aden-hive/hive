"""
LinkedIn ABM Agent - Multi-Channel Outbound Automation.

Orchestrate Account-Based Marketing campaigns across LinkedIn, email,
and direct mail. Features prospecting, data enrichment, message
personalization, human-in-the-loop approval, and campaign tracking.
"""

from .agent import LinkedInABMAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "LinkedInABMAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
