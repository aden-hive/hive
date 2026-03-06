"""
Churn Risk Agent — Detect at-risk customers and trigger proactive retention.

Monitors customer engagement signals, scores churn risk (HIGH / MEDIUM / LOW),
and routes to the correct action: escalation alert, outreach draft with human
approval, or silent monitoring.
"""

from .agent import ChurnRiskAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "ChurnRiskAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
