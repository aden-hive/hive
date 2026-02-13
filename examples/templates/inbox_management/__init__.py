"""
Inbox Management Agent — Manage Gmail inbox using free-text rules.

Apply user-defined rules to inbox emails: trash, mark as spam, mark important,
mark read/unread, star, and more — using only native Gmail actions.
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
