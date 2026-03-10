"""Runtime configuration for Linear Triage & Auto-Labeling Agent."""

import json
from dataclasses import dataclass, field
from pathlib import Path


def _load_preferred_model() -> str:
    """Load preferred model from ~/.hive/configuration.json."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
            llm = config.get("llm", {})
            if llm.get("provider") and llm.get("model"):
                return f"{llm['provider']}/{llm['model']}"
        except Exception:
            pass
    return "anthropic/claude-sonnet-4-20250514"


@dataclass
class RuntimeConfig:
    model: str = field(default_factory=_load_preferred_model)
    temperature: float = 0.3
    max_tokens: int = 16000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Linear Triage & Auto-Labeling Agent"
    version: str = "1.0.0"
    description: str = (
        "Autonomous triage agent that ingests raw issue descriptions, "
        "classifies them (Bug, Feature, Security), determines priority, "
        "and uses a Router Pattern to dispatch to specialized processing nodes."
    )
    intro_message: str = "Welcome! Provide an issue description to triage."


metadata = AgentMetadata()
