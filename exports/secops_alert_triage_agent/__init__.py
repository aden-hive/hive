"""
SecOps Alert Triage Agent - Intelligent Security Alert Correlation,
False Positive Suppression & Escalation.

Ingests security alerts, correlates related events, suppresses false positives,
classifies threats by severity, and escalates with actionable incident briefs.
"""

from .agent import (
    SecOpsAlertTriageAgent,
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

__version__ = "1.0.0"

__all__ = [
    "SecOpsAlertTriageAgent",
    "conversation_mode",
    "default_agent",
    "default_config",
    "edges",
    "entry_node",
    "entry_points",
    "goal",
    "identity_prompt",
    "loop_config",
    "metadata",
    "nodes",
    "pause_nodes",
    "terminal_nodes",
]
