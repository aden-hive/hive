"""Configuration for the B2B Sales Prospecting Agent."""

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
class AgentConfig:
    """Configuration for the Sales Prospecting Agent."""

    model: str = field(default_factory=_load_preferred_model)
    temperature: float = 0.7
    max_tokens: int = 40000
    api_key: str | None = None
    api_base: str | None = None

    # Apollo Search Parameters
    max_leads_per_search: int = 5

    # Enrichment
    enrich_company_info: bool = True

    # Email Settings
    email_provider: str = "resend"
    email_from: str = "sales@example.com"

    # Research Settings
    max_scrape_length: int = 10000

    # LLM Settings
    cleanup_model: str = "claude-3-5-haiku-20241022"


default_config = AgentConfig()


@dataclass
class AgentMetadata:
    name: str = "B2B Sales Prospecting & Outreach"
    version: str = "1.0.0"
    description: str = (
        "Automate the B2B sales workflow: intake target audience, find leads via Apollo, "
        "research companies, draft personalized emails, and send after human approval."
    )


metadata = AgentMetadata()
