"""Runtime configuration for Autonomous SRE Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Autonomous SRE Incident Resolution Agent"
    version: str = "1.0.0"
    description: str = (
        "Autonomous production incident resolution agent that fetches logs, analyzes "
        "root cause, estimates confidence, auto-resolves high-confidence incidents, "
        "and escalates critical or low-confidence incidents to human engineers."
    )
    intro_message: str = (
        "Hi! I'm your autonomous SRE agent. Send me a production alert and I'll "
        "fetch logs, identify the root cause, score my confidence, and either "
        "auto-resolve it or escalate to you with a full investigation summary. "
        "What alert are you seeing?"
    )


metadata = AgentMetadata()
