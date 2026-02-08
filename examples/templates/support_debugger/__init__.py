"""
Support Debugger Agent — Hypothesis-driven investigation of technical support tickets.

Given a support ticket, this agent extracts technical context, generates competing
hypotheses, gathers evidence through investigative tools, refines hypothesis
confidence, and produces a root-cause analysis with actionable fix steps.
"""

from .agent import SupportDebuggerAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "0.1.0"

__all__ = [
    "SupportDebuggerAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
