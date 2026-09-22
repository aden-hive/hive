"""Runtime configuration for Discord Community Digest."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Discord Community Digest"
    version: str = "1.0.0"
    description: str = (
        "Monitor Discord servers, categorize messages by priority, "
        "and deliver an actionable summary to a designated channel."
    )
    intro_message: str = (
        "Hi! I'll create a digest of your Discord community activity. "
        "Tell me which servers to monitor, how far back to look, "
        "and where to deliver the summary."
    )


metadata = AgentMetadata()
