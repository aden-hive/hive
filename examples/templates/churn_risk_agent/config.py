"""Runtime configuration for Churn Risk Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Churn Risk Agent"
    version: str = "1.0.0"
    description: str = (
        "Monitors customer engagement signals, detects churn risk, "
        "and triggers proactive retention actions with human approval."
    )
    intro_message: str = (
        "Hi! I'm your Churn Risk Agent. Provide customer account data "
        "and I'll assess churn risk, escalate high-risk accounts, and "
        "draft re-engagement messages for your review."
    )


metadata = AgentMetadata()
