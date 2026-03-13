"""
Field Service Dispatch Agent - AI-powered field service dispatch with dispatcher approval.

Handles end-to-end dispatch workflow: service request intake, priority triage,
technician matching based on skills and proximity, and coordinated notification
with human-in-the-loop dispatcher approval.
"""

from .agent import FieldServiceDispatchAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "FieldServiceDispatchAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
