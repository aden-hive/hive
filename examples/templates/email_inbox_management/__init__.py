"""
Email Inbox Management Agent — Manage Gmail inbox using free-text rules.

Apply user-defined rules to inbox emails: trash, mark as spam, mark important,
mark read/unread, star, and more — using only native Gmail actions.
"""

from .agent import (
    EmailInboxManagementAgent,
    default_agent,
    goal,
    nodes,
    edges,
    loop_config,
    async_entry_points,
    entry_node,
    entry_points,
    pause_nodes,
    terminal_nodes,
    conversation_mode,
    identity_prompt,
)
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "EmailInboxManagementAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "loop_config",
    "async_entry_points",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
