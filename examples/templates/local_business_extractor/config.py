"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Local Business Extractor"
    version: str = "1.0.0"
    description: str = (
        "Extracts local businesses from Google Maps, scrapes contact details, and syncs the results to Google Sheets."
    )
    intro_message: str = "I'm ready to extract business data. What should I search for?"


metadata = AgentMetadata()
