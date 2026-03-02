#!/bin/bash
# Script to manually run the Hive customer service agent via bash
# This allows direct testing from Git Bash/WSL without the web frontend

HIVE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../hive" && pwd)"
AGENT_INPUT="${1:-I forgot my password}"

echo "[Hive Agent] Starting agent execution via bash..."
echo "[Hive Agent] Hive directory: $HIVE_DIR"
echo "[Hive Agent] User input: '$AGENT_INPUT'"

cd "$HIVE_DIR"

# Set Python environment variable
export PYTHONUNBUFFERED=1

# Run the agent
python -m framework run customer_service_agent --input "$AGENT_INPUT"
