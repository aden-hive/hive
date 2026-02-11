"""
Blog Writer Agent - Business-focused blog pipeline with HITL checkpoints.

Creates a research-backed blog post with positioning, SEO metadata,
quality review, and downloadable artifacts.
"""

from .agent import BlogWriterAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

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
