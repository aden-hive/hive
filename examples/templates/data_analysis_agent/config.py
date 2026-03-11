"""Runtime configuration for Data Analysis Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

default_config: RuntimeConfig = RuntimeConfig()


@dataclass
class AgentMetadata:
    """Metadata for the Data Analysis Agent."""

    name: str = "Data Analysis Agent"
    version: str = "1.0.0"
    description: str = (
        "Analyzes datasets to generate structured insights including summary statistics, "
        "patterns, and trends. Designed to assist users with exploratory data analysis "
        "and quick understanding of dataset characteristics."
    )
    intro_message: str = (
        "Hi! I'm your data analysis assistant. Provide a dataset and I can help analyze it, "
        "generate summary statistics, detect patterns or trends, and produce useful insights."
    )


metadata: AgentMetadata = AgentMetadata()
