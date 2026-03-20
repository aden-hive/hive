"""
Meeting Notes Agent
===================
Parses meeting transcripts to extract structured summaries, decisions,
action items with owners and due dates, blockers, and follow-ups.
Optionally posts results to Slack.

Usage:
    hive run examples.templates.meeting_notes_agent
    python -m examples.templates.meeting_notes_agent
"""

from .agent import MeetingNotesAgent, default_agent, goal, nodes, edges
from .config import RuntimeConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "MeetingNotesAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "RuntimeConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
