"""Runtime configuration for Ticket Triage Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

default_config = RuntimeConfig(
    model="gemini/gemini-1.5-flash",
)

@dataclass
class AgentMetadata:
    name: str = "Ticket Triage Agent"
    version: str = "1.0.0"
    description: str = (
        "Automatically triages incoming customer support tickets by classifying "
        "priority, assigning to the correct team, drafting a first response. "
        "Pauses for human approval on critical tickets."
    )
    intro_message: str = (
        "Hi! I am your support ticket triage assistant. "
        "Send me a support ticket and I will classify it, assign it to the right team, "
        "and draft a response for you."
    )

metadata = AgentMetadata()
