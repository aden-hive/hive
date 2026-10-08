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
        "resume customization lists, cold outreach emails, and Gmail drafts."
    )
    intro_message: str = (
        "Hi! I'm your job hunting assistant. Please upload your resume and I'll "
        "analyze it to identify roles where you have the highest chance of success, "
        "find matching job openings, and create personalized application materials "
        "for the positions you choose — including Gmail drafts ready for you to "
        "review and send. Ready to get started?"
    )


metadata = AgentMetadata()
