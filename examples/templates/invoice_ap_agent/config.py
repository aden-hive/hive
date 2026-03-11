"""Runtime configuration for Invoice & AP Automation Agent."""

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
    name: str = "Invoice & AP Automation Agent"
    version: str = "1.0.0"
    description: str = (
        "End-to-end accounts payable intelligence: extract invoice data, "
        "validate against POs, route for approval, post to accounting systems."
    )
    intro_message: str = (
        "I'll help you process invoices. Provide invoice files or data, "
        "and I'll extract, validate, route for approval, and post to accounting."
    )


metadata = AgentMetadata()
