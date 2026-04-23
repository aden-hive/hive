"""Runtime configuration for Strategic SWOT Analysis Agent."""

from dataclasses import dataclass
from framework.config import RuntimeConfig

default_config: RuntimeConfig = RuntimeConfig()

@dataclass
class AgentMetadata:
    """Metadata for the Strategic SWOT Analysis Agent."""

    name: str = "Strategic SWOT Analysis Agent"
    version: str = "1.0.0"
    description: str = (
        "Autonomous competitor discovery and strategic SWOT synthesis. "
        "Tracks historical deltas to identify shifts in pricing, features, and market positioning."
    )
    intro_message: str = (
        "Hi! I'm your Strategic SWOT Analyst. Tell me your target company, "
        "and I will recursively map out their top competitors, scrape their current offerings, "
        "and generate a formal SWOT matrix."
    )

metadata: AgentMetadata = AgentMetadata()