"""Runtime configuration for SecOps Alert Triage Agent."""

import json
from dataclasses import dataclass, field
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
    temperature: float = 0.2
    max_tokens: int = 32000
    api_key: str | None = None
    api_base: str | None = None


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "SecOps Alert Triage Agent"
    version: str = "1.0.0"
    description: str = (
        "Intelligent security alert triage: correlates alerts, suppresses false positives, "
        "classifies threats by severity, enriches with context, and escalates to on-call engineers."
    )
    intro_message: str = (
        "I'm your SecOps Alert Triage Agent. I'll help you manage security alerts by "
        "correlating related events, filtering false positives, classifying threats, "
        "and escalating critical issues with actionable incident briefs. "
        "Paste an alert or describe what you'd like to triage."
    )


metadata = AgentMetadata()

DEFAULT_SUPPRESSION_RULES = {
    "known_ci_ips": {
        "description": "Known CI/CD IP ranges",
        "ips": ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        "action": "suppress",
    },
    "scheduled_scanners": {
        "description": "Approved vulnerability scanner signatures",
        "user_agents": ["Nessus", "Qualys", "Rapid7"],
        "action": "suppress",
    },
    "maintenance_windows": {
        "description": "Scheduled maintenance periods",
        "windows": [],
        "action": "suppress",
    },
}

DEFAULT_ASSET_CRITICALITY = {
    "production": {"weight": 1.0, "description": "Production systems"},
    "staging": {"weight": 0.7, "description": "Staging environments"},
    "development": {"weight": 0.3, "description": "Development environments"},
    "internal": {"weight": 0.2, "description": "Internal tools"},
}

SEVERITY_THRESHOLDS = {
    "critical": {"min_score": 9.0, "color": "red"},
    "high": {"min_score": 7.0, "color": "orange"},
    "medium": {"min_score": 4.0, "color": "yellow"},
    "low": {"min_score": 0.1, "color": "green"},
}
