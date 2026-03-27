"""Runtime configuration for Meeting Notes Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Meeting Notes Agent"
    version: str = "1.0.0"
    description: str = (
        "Parses meeting transcripts to extract structured summaries, decisions, "
        "action items with owners and due dates, blockers, and follow-ups. "
        "Optionally posts results to Slack."
    )
    intro_message: str = (
        "Hello. I am the Queen, your interface for agent building, coding, and system management.\n\n"
        "I can build new agents, modify existing ones, and manage the worker's lifecycle. "
        "Currently, the Meeting Notes Agent is loaded—it can parse meeting transcripts to extract "
        "structured summaries, decisions, action items with owners and due dates, blockers, and follow-ups.\n\n"
        "What do you need?"
    )


metadata = AgentMetadata()
