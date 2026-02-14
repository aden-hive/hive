"""Runtime configuration for Job Hunter Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Job Hunter"
    version: str = "1.0.0"
    description: str = (
        "Analyze your resume to identify your strongest role fits, find matching "
        "job opportunities, and generate customized application materials including "
        "resume customization lists and cold outreach emails."
    )
    intro_message: str = (
        "Hi! I'm your job hunting assistant. Paste your resume and I'll analyze it to "
        "identify roles where you have the highest chance of success, find matching "
        "job openings, and help you create personalized application materials for "
        "the positions you choose. Ready to get started?"
    )


metadata = AgentMetadata()
