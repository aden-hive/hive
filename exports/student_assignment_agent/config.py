"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Student Assignment Helper Agent"
    version: str = "1.0.0"
    description: str = (
        "An intelligent assignment helper that researches topics, creates structured "
        "outlines, writes academic drafts, reviews quality, and delivers polished "
        "assignments — with student checkpoints at every stage."
    )
    intro_message: str = (
        "Hi! I'm your Student Assignment Helper 📚 Tell me your assignment topic, "
        "subject, word limit, and academic level — and I'll help you write a "
        "well-researched, properly structured assignment. Let's get started!"
    )


metadata = AgentMetadata()
