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
    echo -e "${GREEN}✓ No .mcp.json needed (MCP servers configured at repo root)${NC}"
fi
echo ""

echo -e "${YELLOW}Step 4: Testing framework import...${NC}"
uv run python -c "import framework; print('✓ Framework module loads successfully')" || {
    echo -e "${RED}Failed to import framework module${NC}"
    exit 1
}
echo -e "${GREEN}✓ Framework module verified${NC}"
echo ""

echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "The framework is now ready to use!"
echo ""
echo "MCP Configuration location:"
echo "  $SCRIPT_DIR/.mcp.json"
echo ""
