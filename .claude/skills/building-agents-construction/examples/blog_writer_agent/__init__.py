"""
Blog Writer Agent - SEO-optimized blog post generation.

Research any topic, create structured outlines, and produce polished
markdown blog posts with citations and SEO optimization.
"""

from .agent import BlogWriterAgent, default_agent, edges, goal, nodes
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "BlogWriterAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
