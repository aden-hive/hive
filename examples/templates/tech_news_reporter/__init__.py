"""
Tech & AI News Reporter - Research latest tech/AI news and produce reports.

Searches for recent technology and AI news, summarizes key stories,
and delivers a well-organized HTML report for the user to read.
"""

from .agent import TechNewsReporterAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "TechNewsReporterAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
