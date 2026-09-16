"""Entry point for testing the QA Engineer Agent directly."""

import asyncio
import logging
from .agent import default_agent

# Configure logging to see what the agent is doing
logging.basicConfig(level=logging.INFO)

async def main():
    print("=== Running QA Engineer Agent ===")
    
    # Test message simulating a user request
    test_context = {
        "user_request": "Please run the automated tests in the 'test_project/' directory using 'pytest' and tell me if there are any bugs."
    }
    
    # Run the agent
    result = await default_agent.run(test_context)
    
    print("\n=== Results of execution ===")
    if result.success:
        print("Success!")
    else:
        print(f"Error: {result.error}")

if __name__ == "__main__":
    asyncio.run(main())