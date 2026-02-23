"""
Meeting Notes Agent - Configuration

Supports dual LLM providers: Anthropic Claude and Google Gemini.
The active provider can be overridden at runtime via the 'llm_provider'
input field or the MEETING_AGENT_LLM_PROVIDER environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class AgentConfig:
    """Runtime configuration — matches the interface expected by LiteLLMProvider."""

    model: str = "claude-sonnet-4-5-20250929"
    max_tokens: int = 4096
    temperature: float = 0.1          # Low temperature for factual extraction
    api_key: str | None = None
    api_base: str | None = None

    # Slack defaults
    slack_icon_emoji: str = ":bee:"
    slack_username: str = "Hive Meeting Agent"
    slack_default_channel: str | None = None

    # Storage
    storage_path: str = "/tmp/meeting_notes_agent"

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = (
                os.environ.get("ANTHROPIC_API_KEY")
                or os.environ.get("GEMINI_API_KEY")
            )


@dataclass
class AgentMetadata:
    """Static metadata about this agent."""

    name: str = "Meeting Notes & Action Item Agent"
    version: str = "1.0.0"
    description: str = (
        "Parses meeting transcripts to extract structured summaries, decisions, "
        "action items with owners and due dates, blockers, and follow-ups. "
        "Optionally delivers results to Slack."
    )
    author: str = "RodrigoMvs123"
    tags: list[str] = field(default_factory=lambda: [
        "meetings", "productivity", "slack", "action-items", "nlp"
    ])


# ── Model registry — maps provider names to LiteLLM model strings ────────────
MODEL_REGISTRY: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5-20250929",
    "claude":    "claude-sonnet-4-5-20250929",
    "gemini":    "gemini/gemini-1.5-pro-latest",
    "google":    "gemini/gemini-1.5-pro-latest",
}

# ── Default instances (used by agent.py and nodes.py) ────────────────────────
default_config = AgentConfig()
metadata = AgentMetadata()