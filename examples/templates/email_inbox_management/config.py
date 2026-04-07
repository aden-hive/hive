"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Email Inbox Management Agent"
    version: str = "1.0.0"
    description: str = (
        "Automatically manage Gmail inbox emails using free-text rules. "
        "Trash junk, mark spam, mark important, mark read/unread, star, "
        "draft replies, create/apply custom labels, and more — using only "
        "native Gmail actions."
    )
    intro_message: str = (
        "Hi! I'm your email inbox management assistant. Tell me your rules "
        "(what to trash, mark as spam, mark important, draft replies to, "
        "label with custom labels, etc.) and I'll run an initial triage of "
        "your inbox. After that, I'll automatically check and process new "
        "emails every 5 minutes — so you can set it and forget it. "
        "What rules would you like me to apply?"
    )


metadata = AgentMetadata()
