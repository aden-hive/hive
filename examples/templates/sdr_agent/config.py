"""Configuration for SDR Agent."""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RuntimeConfig:
    """Configuration for the agent runtime."""

    model: str = "claude-3-5-sonnet-20241022"  # Capable model for research/writing
    max_tokens: int = 4096
    storage_path: str = "~/.aden/agents/sdr_agent"
    log_level: str = "INFO"
    
    # SDR Specific settings
    require_web_search: bool = True
    max_research_depth: int = 2


default_config = RuntimeConfig()
