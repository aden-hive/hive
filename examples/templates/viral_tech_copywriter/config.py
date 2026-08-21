"""Runtime configuration for Viral Tech Copywriter."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Viral Tech Copywriter"
    version: str = "1.0.0"
    description: str = (
        "Turns a conversational marketing brief into structured brief JSON, "
        "hook-heavy channel copy, and optional HTML/Markdown exports—without posting "
        "or external research tools."
    )
    intro_message: str = (
        "Hi! I'm your viral tech copywriter. Tell me what you're shipping (product, "
        "audience, proof, tone, and which channels you need). I'll ask one quick "
        "clarifying question if needed, then generate hooks, channel-ready copy, "
        "and your choice of HTML and/or Markdown export."
    )


metadata = AgentMetadata()
