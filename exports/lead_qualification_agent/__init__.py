"""
Lead Qualification Agent - Score, Enrich, and Route Inbound Leads.

Automatically scores, enriches, and routes inbound leads based on Ideal
Customer Profile (ICP) criteria — eliminating manual triage and ensuring
hot leads never slip through the cracks.
"""

from .agent import LeadQualificationAgent, default_agent, edges, goal, nodes
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "LeadQualificationAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
