"""Runtime configuration for Contract Intelligence & Risk Agent."""

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
    temperature: float = 0.2
    max_tokens: int = 32000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Contract Intelligence & Risk Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated contract review and clause risk scoring. "
        "Extracts key clauses, scores risk, flags anomalies, and generates negotiation briefs."
    )
    intro_message: str = (
        "I'll help you review contracts for risk. "
        "Upload a PDF contract or paste contract text, and I'll analyze the clauses, "
        "score risks, and generate a negotiation brief."
    )


metadata = AgentMetadata()

DEFAULT_BASELINE_TEMPLATE = {
    "contract_type": "vendor",
    "payment_terms": {"max_net_days": 30, "preferred": "Net 30"},
    "liability_cap": {
        "max_multiplier": 1.0,
        "preferred": "Fees paid in prior 12 months",
    },
    "indemnification": {"mutual": True, "preferred": "Mutual indemnification"},
    "ip_ownership": {
        "client_retains": True,
        "preferred": "Client owns all deliverables",
    },
    "termination": {
        "notice_days": 30,
        "for_convenience": True,
        "preferred": "30 days notice for any reason",
    },
    "auto_renewal": {
        "requires_notice": True,
        "notice_days": 30,
        "preferred": "No auto-renewal or 30-day opt-out",
    },
    "confidentiality": {
        "mutual": True,
        "survival_years": 3,
        "preferred": "Mutual, 3-year survival",
    },
    "governing_law": {"preferred": "Client jurisdiction or Delaware"},
    "warranties": {
        "standard": True,
        "preferred": "Standard representations and warranties",
    },
    "limitation_of_liability": {
        "excludes_consequential": True,
        "preferred": "Excludes consequential damages",
    },
}
