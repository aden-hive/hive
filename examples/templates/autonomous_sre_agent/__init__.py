"""
Autonomous SRE Incident Resolution Agent.

Accepts production alerts, fetches logs, analyzes root cause, estimates confidence,
auto-resolves high-confidence non-critical incidents, and escalates critical or
low-confidence incidents to human engineers with a full investigation summary.
"""

from .agent import AutonomousSREAgent, default_agent, goal, nodes, edges
from .config import AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "AutonomousSREAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "AgentMetadata",
    "default_config",
    "metadata",
]
