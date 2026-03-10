"""Runtime configuration."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Financial Ledger Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated financial transaction reporting from emails. "
        "Scans Gmail for financial alerts, extracts and categorizes transactions, "
        "and generates monthly Excel ledgers and PDF summary reports."
    )
    intro_message: str = (
        "Hi! I'm your financial ledger assistant. I can scan your email inbox for "
        "financial transactions, categorize them, and generate a detailed monthly report. "
        "Just tell me which month you'd like to analyze, and I'll create an Excel ledger "
        "and a visual summary for you. What date range should I scan?"
    )


metadata = AgentMetadata()
