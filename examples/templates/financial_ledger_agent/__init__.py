"""
Financial Ledger Agent - Automated monthly transaction reporting from emails.

Scans Gmail inbox for financial transaction alerts, extracts and categorizes
transaction data, and generates structured monthly financial summaries in
Excel and PDF formats.
"""

from .agent import (
    FinancialLedgerAgent,
    default_agent,
    goal,
    nodes,
    edges,
    entry_node,
    entry_points,
    loop_config,
    identity_prompt,
)
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "FinancialLedgerAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "entry_node",
    "entry_points",
    "loop_config",
    "identity_prompt",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
