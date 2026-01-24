#!/bin/bash

# Setup script for Aden Hive Framework MCP Server
# This script installs the framework and configures the MCP server

set -e

# Colors for output
NC=$'\e[0m' # No Color
BOLD=$'\e[1m'
RED=$'\e[91m'
GREEN=$'\e[92m'
YELLOW=$'\e[93m'

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd "$SCRIPT_DIR"

warn () { echo "$YELLOW$*$NC"; } >&2

die () { echo "$RED$*$NC"; exit 1; } >&2

echo "$BOLD=== Aden Hive Framework MCP Server Setup ===$NC"
echo

warn "Step 1: Installing framework package..."
pip install -e . || die "Failed to install framework package"
echo "$GREEN✓ Framework package installed$NC"
echo

warn "Step 2: Installing MCP dependencies..."
pip install mcp fastmcp || die "Failed to install MCP dependencies"
echo "$GREEN✓ MCP dependencies installed$NC"
echo

warn "Step 3: Verifying MCP server configuration..."
if [ -f ".mcp.json" ]; then
  echo "$GREEN✓ MCP configuration found at .mcp.json$NC"
  echo "Configuration:"
  cat .mcp.json
else
  echo "$RED✗ No .mcp.json found$NC"
  echo "Creating default MCP configuration..."

  cat > .mcp.json <<EOF
{
  "mcpServers": {
    "agent-builder": {
      "command": "python",
      "args": ["-m", "framework.mcp.agent_builder_server"],
      "cwd": "$SCRIPT_DIR"
    }
  }
}
EOF
  echo "$GREEN✓ Created .mcp.json$NC"
fi
echo

warn "Step 4: Testing MCP server..."
python -c "from framework.mcp import agent_builder_server; \
print('✓ MCP server module loads successfully')" ||
  die "Failed to import MCP server module"
echo "$GREEN✓ MCP server module verified$NC"
echo

echo "$GREEN=== Setup Complete ===$NC"
echo
echo "The MCP server is now ready to use!"
echo
echo "To start the MCP server manually:"
echo "  python -m framework.mcp.agent_builder_server"
echo
echo "MCP Configuration location:"
echo "  $SCRIPT_DIR/.mcp.json"
echo
echo "To use with Claude Desktop or other MCP clients,"
echo "add the following to your MCP client configuration:"
echo
echo "{
  \"mcpServers\": {
    \"agent-builder\": {
      \"command\": \"python\",
      \"args\": [\"-m\", \"framework.mcp.agent_builder_server\"],
      \"cwd\": \"$SCRIPT_DIR\"
    }
  }
}"
echo
