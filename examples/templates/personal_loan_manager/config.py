"""Configuration for Personal Loan Manager."""
from dataclasses import dataclass
from framework.llm import LLMConfig

@dataclass
class AgentMetadata:
    name: str = "personal_loan_manager"
    version: str = "1.0.0"
    description: str = "Automates BFSI personal loan approval workflows."

metadata = AgentMetadata()
default_config = LLMConfig()