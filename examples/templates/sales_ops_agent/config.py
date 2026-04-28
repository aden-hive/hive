"""Runtime configuration for Sales Ops Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Sales Ops Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated sales territory rebalancing agent. Runs monthly to analyze "
        "sales performance, detect under-allocated territories (less than 20% "
        "untouched ICP accounts), and rebalance accounts from unassigned pools. "
        "Supports Salesforce and HubSpot CRM integration via MCP."
    )
    intro_message: str = (
        "Hi! I'm your Sales Operations assistant. I help maintain fair and "
        "balanced territory distribution across your sales team. On the 1st of "
        "each month, I analyze pipeline metrics, win rates, and TAM coverage, "
        "then reassign accounts from unassigned pools to reps who need more "
        "opportunities. All actions are logged to your CRM for auditability."
    )


metadata = AgentMetadata()
