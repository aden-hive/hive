"""
Blog Writer Agent - Research and write complete blog posts.

Given a topic, this agent searches for supporting facts, creates a structured
outline, writes a full draft, reviews and refines it, and saves a polished
markdown file to ./blog_posts/.
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
