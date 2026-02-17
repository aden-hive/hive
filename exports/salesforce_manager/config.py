"""
Configuration for the Salesforce Manager Agent.
"""

from dataclasses import dataclass

@dataclass
class AgentMetadata:
    name: str = "Salesforce Manager"
    description: str = "An agent that interacts with Salesforce CRM to manage leads, contacts, and opportunities."
    intro_message: str = "Hello! I'm your Salesforce Manager. I can help you search for leads, create records, and run custom SOQL queries. What would you like to do today?"
    version: str = "1.0.0"

# Model settings
DEFAULT_MODEL = "claude-3-5-sonnet-latest"
MAX_TOKENS = 4096
TEMPERATURE = 0.0
