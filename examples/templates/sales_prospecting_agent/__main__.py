"""Main entry point for running the Sales Prospecting Agent locally."""

import asyncio
import logging
import sys
from .agent import SalesProspectingAgent

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)


async def main():
    agent = SalesProspectingAgent()
    print("Starting B2B Sales Prospecting Agent...")
    print(
        "Workflow: Intake -> Lead Search -> Company Research -> Draft Email -> Human Approval -> Send Email"
    )
    print("-" * 50)

    result = await agent.run()

    if result.success:
        print("\nCampaign finished successfully!")
        print(f"Final Output: {result.output}")
    else:
        print(f"\nCampaign failed: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
