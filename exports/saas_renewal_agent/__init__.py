"""
SaaS Renewal & Upsell Agent - Proactive Revenue Expansion Through Usage Intelligence.

Monitor subscription data for upcoming renewals, usage drop signals, and expansion
opportunities. Generate personalized outreach drafted for account manager review
and approval to maximize Net Revenue Retention (NRR).
"""

from .agent import SaaSRenewalAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "SaaSRenewalAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
