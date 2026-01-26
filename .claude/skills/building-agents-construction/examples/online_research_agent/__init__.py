"""
Online Research Agent - Deep-dive research with narrative reports.

Research any topic by searching multiple sources, synthesizing information,
and producing a well-structured narrative report with citations.
"""

from .agent import OnlineResearchAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "OnlineResearchAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
