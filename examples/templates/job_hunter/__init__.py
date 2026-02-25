"""
Job Hunter Agent - Find jobs and create personalized application materials.

Analyze your resume to identify your strongest role fits, search for matching
job opportunities, and generate customized resume customization lists and
cold outreach emails for each position you select.
"""

from .agent import JobHunterAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "JobHunterAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
