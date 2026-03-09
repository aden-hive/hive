"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Sales Call News Researcher"
    version: str = "1.0.0"
    description: str = (
        "Automatically prepares personalized company news briefings before sales calls. "
        "Scans your Google Calendar for upcoming meetings, identifies companies, fetches "
        "recent news, curates top articles, and sends briefing emails to help you walk "
        "into every meeting informed about your prospect's latest developments."
    )
    intro_message: str = (
        "Hi! I'm your sales call news researcher. I'll scan your calendar for upcoming "
        "sales calls, research the companies you're meeting with, and send you briefing "
        "emails with relevant news before each call. Just tell me when you're ready to "
        "start, or provide a specific date range to scan."
    )


metadata = AgentMetadata()
