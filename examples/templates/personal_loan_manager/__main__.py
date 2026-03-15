"""Entry point for the Personal Loan Manager."""
import asyncio
from .agent import default_agent

if __name__ == "__main__":
    asyncio.run(default_agent.start())