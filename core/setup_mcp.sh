#!/bin/bash

# Setup script for Aden Hive Framework MCP Server
# This script installs the framework and configures the MCP server

set -e  # Exit on error

echo "=== Aden Hive Framework MCP Server Setup ==="
echo ""

# Color codes for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo -e "${YELLOW}Step 1: Installing framework package...${NC}"
uv pip install -e . || {
    echo -e "${RED}Failed to install framework package${NC}"
    exit 1
}
echo -e "${GREEN}✓ Framework package installed${NC}"
echo ""

echo -e "${YELLOW}Step 2: Installing MCP dependencies...${NC}"
uv pip install mcp fastmcp || {
    echo -e "${RED}Failed to install MCP dependencies${NC}"
    exit 1
}
echo -e "${GREEN}✓ MCP dependencies installed${NC}"
echo ""

echo -e "${YELLOW}Step 3: Verifying MCP server configuration...${NC}"
if [ -f ".mcp.json" ]; then
    echo -e "${GREEN}✓ MCP configuration found at .mcp.json${NC}"
    echo "Configuration:"
    cat .mcp.json
else
    echo -e "${RED}✗ No .mcp.json found${NC}"
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
    echo -e "${GREEN}✓ Created .mcp.json${NC}"
fi
echo ""

echo -e "${YELLOW}Step 4: Testing MCP server...${NC}"
uv run python -c "from framework.mcp import agent_builder_server; print('✓ MCP server module loads successfully')" || {
    echo -e "${RED}Failed to import MCP server module${NC}"
    exit 1
}
echo -e "${GREEN}✓ MCP server module verified${NC}"
echo ""

echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "The MCP server is now ready to use!"
echo ""
echo "To start the MCP server manually:"
echo "  uv run python -m framework.mcp.agent_builder_server"
echo ""
echo "MCP Configuration location:"
echo "  $SCRIPT_DIR/.mcp.json"
echo ""
echo "To use with Claude Desktop or other MCP clients,"
echo "add the following to your MCP client configuration:"
echo ""
echo "{
  \"mcpServers\": {
    \"agent-builder\": {
      \"command\": \"python\",
      \"args\": [\"-m\", \"framework.mcp.agent_builder_server\"],
      \"cwd\": \"$SCRIPT_DIR\"
    }
  }
}"
echo ""
