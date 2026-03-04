"""
Universal Document Intake & Action Agent

A Hive agent that accepts any business document (invoices, contracts, receipts,
bank statements, forms), extracts structured data, classifies the document type,
validates the extracted data, and routes it to the appropriate workflow.
"""

from .agent import (
    DocumentIntakeAgent, default_agent, goal, nodes, edges,
    entry_node, entry_points, pause_nodes, terminal_nodes,
    conversation_mode, identity_prompt, loop_config,
    default_config, metadata,
)

__version__ = "0.1.0"

__all__ = [
    "DocumentIntakeAgent",
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
]