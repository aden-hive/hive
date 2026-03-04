"""Runtime configuration for Hacker News Briefing Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Hacker News Briefing Agent"
    version: str = "1.0.0"
    description: str = (
        "Generates a daily Hacker News briefing with ranked stories, source links, "
        "and concise why-it-matters notes."
    )
    intro_message: str = (
        "Share your briefing preferences (story count, scope, channels, timezone/time) "
        "and I will generate your Hacker News briefing."
    )


metadata = AgentMetadata()
