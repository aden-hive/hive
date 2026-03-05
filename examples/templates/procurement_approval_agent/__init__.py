"""Procurement Approval Agent package."""

from .agent import (
    ProcurementApprovalAgent,
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
from .config import default_config, metadata
from .monitor import RequestMonitor

__version__ = "1.0.0"

__all__ = [
    "ProcurementApprovalAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "pause_nodes",
    "terminal_nodes",
    "conversation_mode",
    "identity_prompt",
    "loop_config",
    "default_config",
    "metadata",
    "RequestMonitor",
]
