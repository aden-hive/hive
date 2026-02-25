"""
Curriculum Research Agent — ADDIE-based content brief generation pipeline.

Research current industry standards for a given topic, align findings to
learning outcomes, and produce a structured content brief ready for
instructional design.
"""

from .agent import CurriculumResearchAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "CurriculumResearchAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
