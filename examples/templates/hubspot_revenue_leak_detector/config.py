"""Runtime configuration for HubSpot Revenue Leak Detector Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

VERSION = "1.0.0"

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "HubSpot Revenue Leak Detector"
    version: str = VERSION
    description: str = (
        "Autonomous HubSpot CRM monitor that detects revenue leaks — "
        "ghosted prospects, stalled deals, overdue invoices, and churn risk — "
        "across continuous monitoring cycles. Requires HUBSPOT_ACCESS_TOKEN."
    )
    intro_message: str = (
        "HubSpot Revenue Leak Detector is running. "
        "Scanning pipeline for revenue leaks..."
    )


metadata = AgentMetadata()
