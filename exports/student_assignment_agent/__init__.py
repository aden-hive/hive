"""
Student Assignment Helper Agent - AI-powered academic assignment writer.

Helps students complete well-researched, properly structured assignments
on any topic. Features student checkpoints for outline approval and draft
review, with final delivery as a polished HTML document.
"""

from .agent import StudentAssignmentAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "StudentAssignmentAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
