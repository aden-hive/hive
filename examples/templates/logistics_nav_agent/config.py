from dataclasses import dataclass
from typing import Any

@dataclass
class RuntimeConfig:
    model: str = "gemini/gemini-3.1-flash-lite-preview"
    api_key: str | None = None
    api_base: str | None = None
    max_tokens: int = 4096

@dataclass
class Metadata:
    name: str = "Logistics Navigation Agent"
    version: str = "1.0.0"
    description: str = "Agent for smart route planning with POI detection and navigation sync."

default_config = RuntimeConfig()
metadata = Metadata()
