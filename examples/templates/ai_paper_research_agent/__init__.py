"""
AI Paper Research Agent - Deep research template for difficult ML papers.

Designed for researchers who need help understanding recent large AI papers,
including paper discovery, technical breakdown, synthesis, and guided learning.
"""

from .agent import AIPaperResearchAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "AIPaperResearchAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
