"""CLI entry point for Marketing Content Agent."""

import asyncio
import json
import sys


def main():
    from .agent import MarketingAgent
    from .config import default_config

    # Simple CLI — replace with Click for production use
    input_data = {
        "product_description": "An AI-powered project management tool for remote teams",
        "target_audience": "Engineering managers at mid-size tech companies",
        "brand_voice": "Professional but approachable, concise, data-driven",
        "channels": ["email", "twitter", "linkedin"],
    }

    # Accept JSON input from command line
    if len(sys.argv) > 1 and sys.argv[1] == "--input":
        input_data = json.loads(sys.argv[2])

    agent = MarketingAgent(config=default_config)
    result = asyncio.run(agent.run(input_data))

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
