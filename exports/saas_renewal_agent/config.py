"""Runtime configuration for SaaS Renewal & Upsell Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "SaaS Renewal & Upsell Agent"
    version: str = "1.0.0"
    description: str = (
        "Proactive revenue expansion agent that monitors subscription data, "
        "classifies accounts by renewal risk or expansion opportunity, drafts "
        "personalized outreach for account manager review, and generates NRR reports."
    )
    intro_message: str = (
        "Hi! I'm your SaaS Renewal & Upsell Agent. I monitor subscription data, "
        "identify renewal risks and expansion opportunities, and draft personalized "
        "outreach emails for your review. Share your subscription data (CSV/Excel) "
        "and usage metrics, and I'll help maximize your Net Revenue Retention."
    )


metadata = AgentMetadata()
