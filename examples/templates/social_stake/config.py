"""Runtime configuration for SocialStake Agent."""

from dataclasses import dataclass

from framework.config import RuntimeConfig

default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    name: str = "SocialStake"
    version: str = "1.0.0"
    description: str = (
        "AI-governed financial accountability protocol that helps users improve social skills "
        "by staking USDC that only an AI Arbiter can release based on verified real-world "
        "interactions. Features daily check-ins, verification via meeting reports and "
        "photo proofs, and on-chain settlement."
    )
    intro_message: str = (
        "Welcome to SocialStake! I'm your AI accountability partner. Set a social goal, "
        "stake some USDC, and I'll help you stay on track with daily reminders and verification. "
        "When you complete your social challenges, I'll release your stake back to you. "
        "Ready to commit to improving your social skills?"
    )


metadata = AgentMetadata()
