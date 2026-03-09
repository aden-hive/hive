"""
OSS Lead Intelligence Agent - Configuration.

Runtime configuration and metadata for the Open-Source Lead Intelligence agent.
"""

from dataclasses import dataclass, field
import json
from pathlib import Path


def _load_preferred_model() -> str:
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
    temperature: float = 0.7
    max_tokens: int = 8000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "OSS Lead Intelligence"
    version: str = "1.0.0"
    description: str = (
        "Transform GitHub repository interest signals (stars, forks, contributions) "
        "into qualified CRM contacts with enrichment data and team notifications."
    )
    intro_message: str = (
        "Welcome to OSS Lead Intelligence! I'll help you identify high-value leads "
        "from your GitHub repository stargazers and contributors. Let's start by "
        "configuring your target repositories and ideal customer profile."
    )


metadata = AgentMetadata()
