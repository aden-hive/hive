"""
Gmail Inbox Guardian - Event-driven Gmail triage with user-defined rules.

Define free-text rules for email triage and the agent automatically applies them
to incoming emails when triggered by external events (webhooks, manual triggers).
"""

from .agent import (
    GmailInboxGuardianAgent,
    default_agent,
    goal,
    nodes,
    edges,
    async_entry_points,
    runtime_config,
)
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "GmailInboxGuardianAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "async_entry_points",
    "runtime_config",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
