"""
GitHub Issue Triage Agent - Automated issue classification and routing.

Monitors a GitHub repository for open issues, classifies them by type
(bug, feature, question, duplicate), applies labels, posts triage comments,
and sends notifications to Slack/Discord.
"""

from .agent import GitHubIssueTriageAgent, default_agent, goal, nodes, edges
from .config import AgentConfig, AgentMetadata, default_config, metadata

__version__ = "1.0.0"

__all__ = [
    "GitHubIssueTriageAgent",
    "default_agent",
    "goal",
    "nodes",
    "edges",
    "AgentConfig",
    "AgentMetadata",
    "default_config",
    "metadata",
]
