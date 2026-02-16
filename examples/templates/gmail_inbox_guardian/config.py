"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Gmail Inbox Guardian"
    version: str = "1.0.0"
    description: str = (
        "Event-driven Gmail inbox agent. Define free-text rules for email triage "
        "(star, spam, trash, mark read/unread, label, etc.) and the agent automatically "
        "applies them to incoming emails when triggered by external events."
    )
    intro_message: str = (
        "Hi! I'm your Gmail Inbox Guardian. Tell me your email triage rules "
        "in plain language (e.g., 'star emails from my boss', 'spam newsletters') "
        "and I'll automatically apply them to your inbox."
    )


metadata = AgentMetadata()
