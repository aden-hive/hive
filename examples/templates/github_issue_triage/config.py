"""Runtime configuration for GitHub Issue Triage Agent."""

from dataclasses import dataclass, field

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentConfig:
    """User-configurable settings for the GitHub Issue Triage Agent.

    SECURITY — Fill in owner and repo before running the agent.
    Leave allowed_repos empty to permit any valid repo, or set it
    to an explicit list (e.g. ["your-org/your-repo"]) so the agent
    hard-refuses acting on any other repository.

    NOTIFICATIONS — Set slack_channel and discord_channel_id to your
    channel IDs. Leave empty to skip notifications for that platform.
    Tokens are read from SLACK_BOT_TOKEN / DISCORD_BOT_TOKEN env vars.
    """

    # --- Target repository (required) ---
    owner: str = ""              # GitHub org or user, e.g. "my-org"
    repo: str = ""               # Repository name, e.g. "my-repo"

    # --- Security allowlist ---
    allowed_repos: list[str] = field(default_factory=list)
    # If non-empty, ONLY these repos can be acted on.
    # Recommended for production: ["your-org/your-repo"]

    # --- Notification channels (optional) ---
    slack_channel: str = ""          # Slack channel ID, e.g. "C01234ABCDE"
    discord_channel_id: str = ""     # Discord channel ID, e.g. "1234567890"

    # --- Polling & limits ---
    interval_minutes: int = 30       # Timer interval for polling
    max_issues_per_run: int = 50     # Cap per run to avoid rate limits
    triage_label: str = "needs-triage"  # Label marking un-triaged issues


@dataclass
class AgentMetadata:
    name: str = "GitHub Issue Triage Agent"
    version: str = "1.0.0"
    description: str = (
        "An agent that monitors a GitHub repository for open issues, "
        "automatically classifies them by type (bug, enhancement, question, duplicate), "
        "applies labels, posts triage comments, and sends Slack/Discord notifications."
    )
    intro_message: str = (
        "Hi! I'm your GitHub Issue Triage assistant.\n\n"
        "**Setup (one time):**\n"
        "1. Set `owner` and `repo` in `config.py`\n"
        "2. Set `SLACK_BOT_TOKEN` / `DISCORD_BOT_TOKEN` env vars and add channel IDs\n"
        "3. Optionally set `allowed_repos` to lock the agent to specific repos\n\n"
        "Then click **Run** — I'll fetch open issues, classify them, "
        "apply labels, post triage comments, and notify your team."
    )


agent_config = AgentConfig()
metadata = AgentMetadata()
