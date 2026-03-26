"""Runtime configuration for SDR Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "SDR Agent"
    version: str = "1.0.0"
    description: str = (
        "Automate sales development outreach using AI-powered contact scoring, "
        "scam detection, and personalized message generation. "
        "Score contacts by priority, filter suspicious profiles, generate "
        "personalized outreach messages, and create Gmail drafts for review."
    )
    intro_message: str = (
        "Hi! I'm your SDR (Sales Development Representative) assistant. "
        "Provide a list of contacts and your outreach goal, and I'll "
        "score them by priority, filter out suspicious profiles, generate "
        "personalized messages for each contact, and create Gmail drafts "
        "for your review. I never send emails automatically — you stay in control. "
        "To get started, share your contact list and tell me about your outreach goal!"
    )


metadata = AgentMetadata()
