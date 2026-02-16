"""Runtime configuration for Contract Evaluation Agent."""

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
    temperature: float = 0.3  # Lower temperature for more consistent legal analysis
    max_tokens: int = 40000
    api_key: str | None = None
    api_base: str | None = None
    # Risk threshold for human review escalation
    risk_threshold: float = 7.0
    # Enable detailed logging for debugging
    verbose: bool = False


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Contract Evaluation Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated NDA analysis agent that extracts key information, identifies "
        "risk factors, checks compliance, and generates structured reports. "
        "Escalates high-risk contracts to human reviewers using HITL capabilities."
    )
    contract_types_supported: list[str] = field(
        default_factory=lambda: ["NDA", "Non-Disclosure Agreement"]
    )


metadata = AgentMetadata()
