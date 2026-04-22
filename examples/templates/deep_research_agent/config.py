"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Deep Research Agent"
    version: str = "1.1.0"  
    description: str = (
        "Interactive research agent that rigorously investigates topics through "
        "multi-source search, quality evaluation, and synthesis - with TUI conversation "
        "at key checkpoints for user guidance and feedback."
    )
    intro_message: str = (
       intro_message: str = (
    "Hi! I'm your Deep Research Agent \n"
    "Here's how I work:\n"
    "  1. You give me a topic\n"
    "  2. I search multiple authoritative sources\n"
    "  3. I show you my findings and ask if you want to dig deeper\n"
    "  4. I write you a fully cited HTML report\n\n"
    "Every claim I make traces back to a real source — no hallucination.\n\n"
    "What would you like me to research today?"
)
    )


metadata = AgentMetadata()
