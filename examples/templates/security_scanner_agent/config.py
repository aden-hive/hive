"""Runtime configuration for Security Code Scanner Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "Security Code Scanner Agent"
    version: str = "1.0.0"
    description: str = (
        "Automated security audit agent that scans codebases for vulnerabilities, "
        "scores risks, and generates professional security reports with prioritized "
        "remediation plans."
    )
    intro_message: str = (
        "Hi! I'm your security code scanner. Point me at a codebase and I'll "
        "analyze it for vulnerabilities — checking for injection flaws, hardcoded "
        "secrets, broken auth, and more. I'll produce a risk-scored report with "
        "actionable fixes. What code would you like me to scan?"
    )


metadata = AgentMetadata()
