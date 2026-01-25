# Hello World Agent

A minimal example agent for the Hive platform. This agent demonstrates the basic structure of Hive agents and serves as a starting point for new users.

## Quick Start

### All Platforms (Linux/Mac)
```bash
# Validate the agent structure
PYTHONPATH=core:exports python -m hello_world_agent validate

# Get agent information
PYTHONPATH=core:exports python -m hello_world_agent info

# Run the agent
PYTHONPATH=core:exports python -m hello_world_agent run --input '{"name": "Alice"}'