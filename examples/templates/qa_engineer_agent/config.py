"""Runtime configuration for the QA Engineer Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

default_config = RuntimeConfig()

@dataclass
class AgentMetadata:
    name: str = "QA Engineer Agent"
    version: str = "1.0.0"
    description: str = (
        "Advanced Quality Assurance agent capable of analyzing requirements, "
        "executing automated test suites (Robot Framework, Java, Playwright, etc.), "
        "performing exploratory UI testing via browser tools, and reporting bugs."
    )
    intro_message: str = (
        "Hello! I am your QA Engineer Agent. Please provide the repository path, "
        "the test commands to run (e.g., 'robot tests/' or 'mvn test'), or a URL "
        "for exploratory UI testing. I will execute the tests, analyze the logs, "
        "and provide a detailed bug report."
    )

metadata = AgentMetadata()