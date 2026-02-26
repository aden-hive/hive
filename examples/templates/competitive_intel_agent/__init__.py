"""
Competitive Intelligence Agent — Automated competitor monitoring and reporting.

Monitors competitor websites, news sources, and GitHub repositories to deliver
structured weekly digests with key insights and 30-day trend analysis for
product and marketing teams.
"""

from .agent import CompetitiveIntelAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "CompetitiveIntelAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
