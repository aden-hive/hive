"""
Revenue Leak Detector Agent — Autonomous business health monitor.

Continuously scans a CRM pipeline, detects revenue leaks (ghosted prospects,
stalled deals, overdue invoices, churn risk), sends structured alerts via
Telegram, and emails GHOSTED contacts via Gmail.
"""

from .agent import RevenuLeakDetectorAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "RevenuLeakDetectorAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
