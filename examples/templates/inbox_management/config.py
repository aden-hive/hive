"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Inbox Management Agent"
    version: str = "1.0.0"
    description: str = (
        "Automatically triage unread Gmail emails using free-text rules. "
        "Trash spam, archive low-priority, mark important, and categorize "
        "by urgency (Action Needed, FYI, Waiting On)."
    )
    intro_message: str = (
        "Hi! I'm your inbox management assistant. Tell me your triage rules "
        "(what to trash, archive, mark important) and I'll sort through your "
        "unread emails. How would you like me to manage your inbox?"
    )


metadata = AgentMetadata()
