"""
Inbox Management Agent — Automatic email triage using free-text rules.

Triage unread Gmail emails by trashing spam, archiving low-priority,
marking important, and categorizing by urgency (Action Needed, FYI, Waiting On).
"""

from .agent import InboxManagementAgent, default_agent, goal, nodes, edges, loop_config
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "InboxManagementAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "loop_config",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
