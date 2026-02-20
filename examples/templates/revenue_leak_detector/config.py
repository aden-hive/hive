"""Runtime configuration for Revenue Leak Detector Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig


default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Revenue Leak Detector"
    version: str = "1.0.0"
    description: str = (
        "Autonomous business health monitor that detects revenue leaks — "
        "ghosted prospects, stalled deals, overdue invoices, and churn risk — "
        "across continuous CRM monitoring cycles."
    )
    intro_message: str = (
        "Revenue Leak Detector is running. "
        "Scanning pipeline for revenue leaks..."
    )


metadata = AgentMetadata()
