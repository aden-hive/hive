""" Runtime configuration for Data Analysis Agent. """

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()

@dataclass
class AgentMetaData:
    name: str = "Data Analysis Agent"
    version: str = "0.1.0"
    description: str = (
        "Agent that analyzes structured datasetd and generates statistical insights" \
        "such as row counts, column information and numeric summaries."
    )
    intro_message: str = (
        "Hi! I'm your data analysis assistant. Provide me a dataset path, and I will " \
        "analyze the data and generate a statistical summary."
    )

metadata = AgentMetaData()
