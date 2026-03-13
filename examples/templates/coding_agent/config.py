"""Configuration for Coding Agent."""

from dataclasses import dataclass

@dataclass
class RuntimeConfig:
    """Configuration for the agent runtime."""
    model: str = "claude-3-5-sonnet-20241022"
    max_tokens: int = 8192
    storage_path: str = "~/.aden/agents/coding_agent"
    log_level: str = "INFO"

default_config = RuntimeConfig()
