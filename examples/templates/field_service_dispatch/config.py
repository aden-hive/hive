"""Runtime configuration for Field Service Dispatch Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Field Service Dispatch Agent"
    version: str = "1.0.0"
    description: str = (
        "AI-powered field service dispatch agent that handles service request intake, "
        "priority triage, technician matching with proximity-based routing, and "
        "automated customer/technician notification — with dispatcher approval at "
        "the final step."
    )
    intro_message: str = (
        "Hi! I'm your field service dispatch assistant. Describe the service issue "
        "and I'll handle triage, find the best available technician, and coordinate "
        "the dispatch. What's the service request?"
    )


metadata = AgentMetadata()
