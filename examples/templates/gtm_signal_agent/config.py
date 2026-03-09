"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "GTM Signal Intelligence Agent"
    version: str = "1.0.0"
    description: str = (
        "Forever-alive agent that monitors GTM signals, enriches leads, "
        "scores opportunities, and drafts outreach with human-in-the-loop approval."
    )
    intro_message: str = (
        "Hi! I'm your GTM Signal Intelligence Agent. I continuously scan for buying "
        "signals, enrich leads, and prepare targeted outreach. What is our Ideal "
        "Customer Profile (ICP) for this session?"
    )


metadata = AgentMetadata()
