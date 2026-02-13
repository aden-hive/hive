"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Inbox Management Agent"
    version: str = "1.0.0"
    description: str = (
        "Automatically manage Gmail inbox emails using free-text rules. "
        "Trash junk, mark spam, mark important, mark read/unread, star, "
        "and more — using only native Gmail actions."
    )
    intro_message: str = (
        "Hi! I'm your inbox management assistant. Tell me your rules "
        "(what to trash, mark as spam, mark important, etc.) and I'll sort "
        "through your emails. How would you like me to manage your inbox?"
    )


metadata = AgentMetadata()
