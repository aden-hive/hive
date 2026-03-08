"""
SocialStake Agent - AI-governed financial accountability protocol.

Helps users improve social skills by staking USDC that only an AI Arbiter
can release based on verified real-world interactions. Features daily
check-ins, verification via meeting reports and photo proofs, and
on-chain settlement.
"""

from .agent import (
    SocialStakeAgent,
    async_entry_points,
    conversation_mode,
    default_agent,
    edges,
    entry_node,
    entry_points,
    goal,
    identity_prompt,
    loop_config,
    nodes,
    pause_nodes,
    terminal_nodes,
)
from .config import AgentMetadata, RuntimeConfig, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "SocialStakeAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "async_entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "loop_config",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
