"""
Study Planner Agent - Generates day-wise study schedules based on
subjects, deadlines, difficulty, and available time.
"""

from .agent import StudyPlannerAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "StudyPlannerAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
