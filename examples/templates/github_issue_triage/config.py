"""Runtime configuration for GitHub Issue Triage Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentConfig:
    """User-configurable settings for the GitHub Issue Triage Agent."""

    owner: str = ""  # GitHub org or user, e.g. "adenhq"
    repo: str = ""  # Repository name, e.g. "hive"
    slack_channel: str = "#eng-issues"  # Slack channel for notifications
    discord_channel_id: str = ""  # Optional Discord channel ID
    interval_minutes: int = 30  # Timer interval for polling
    max_issues_per_run: int = 50  # Cap to avoid rate limits
    triage_label: str = "needs-triage"  # Label marking un-triaged issues


@dataclass
class AgentMetadata:
    name: str = "GitHub Issue Triage Agent"
    version: str = "1.0.0"
    description: str = (
        "A forever-alive agent that monitors a GitHub repository for open issues, "
        "automatically classifies them by type (bug, enhancement, question, duplicate), "
        "applies labels, posts triage comments, and sends Slack/Discord notifications."
    )
    intro_message: str = (
        "Hi! I'm your GitHub Issue Triage assistant. I'll monitor your repository "
        "for new issues, classify them, apply labels, and notify your team. "
        "Tell me which repository to watch (owner/repo)."
    )


agent_config = AgentConfig()
metadata = AgentMetadata()
