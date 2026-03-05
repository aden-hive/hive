"""Runtime configuration for Lead Qualification Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Lead Qualification Agent"
    version: str = "1.0.0"
    description: str = (
        "Automatically scores, enriches, and routes inbound leads based on "
        "Ideal Customer Profile (ICP) criteria — eliminating manual triage and "
        "ensuring hot leads never slip through the cracks."
    )
    intro_message: str = (
        "Hi! I'm your Lead Qualification Agent. Give me a lead (name, email, company, role) "
        "and I'll enrich it with firmographic data, score it against your ICP, and route it "
        "to the right pipeline. What lead would you like me to qualify?"
    )


metadata = AgentMetadata()
