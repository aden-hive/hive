"""Runtime configuration for Issue Triage Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Issue Triage Agent"
    version: str = "1.0.0"
    description: str = (
        "Triages incoming support and bug signals from Discord, Gmail, and GitHub "
        "into a single prioritized queue, routes high-priority items, and updates "
        "GitHub issues with consistent labels and status."
    )
    intro_message: str = (
        "I can triage issues across Discord, email, and GitHub. "
        "Tell me your repo, Discord channels, and triage policy, and I will run "
        "a cross-channel triage pass and post a summary."
    )


metadata = AgentMetadata()
