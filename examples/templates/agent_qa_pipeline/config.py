"""Configuration for Agent QA Pipeline."""

import os
from dataclasses import dataclass


@dataclass
class AgentQAPipelineConfig:
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    api_key: str | None = None
    api_base: str | None = None
    max_feedback_cycles: int = 3

    def __post_init__(self):
        if self.api_key is None:
            self.api_key = os.getenv("ANTHROPIC_API_KEY")


default_config = AgentQAPipelineConfig()
