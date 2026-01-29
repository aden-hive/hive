#!/bin/bash
#
# quickstart.sh - Complete setup for Aden Agent Framework
#
# This is the PRIMARY setup script for the Aden Agent Framework.
# It sets up the Python environment and optionally installs Claude Code skills.
#
# Usage:
#   ./quickstart.sh              # Full setup with Claude skills
#   ./quickstart.sh --headless   # Python environment only (no Claude skills)
#
# For headless/server environments where Claude Code is not needed,
# use: ./scripts/setup-python.sh directly.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Parse arguments
HEADLESS_MODE=false
for arg in "$@"; do
    case $arg in
        --headless)
            HEADLESS_MODE=true
            shift
            ;;
    esac
done

# Claude Code skills directory
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"

echo ""
echo "=================================================="
echo "  Aden Agent Framework - Complete Setup"
echo "=================================================="
echo ""

# ============================================================
# Step 1: Run Python Environment Setup
# ============================================================

echo -e "${BLUE}Step 1: Setting up Python environment...${NC}"
echo ""

# Run setup-python.sh for all Python environment setup
if [ -f "$SCRIPT_DIR/scripts/setup-python.sh" ]; then
    if ! bash "$SCRIPT_DIR/scripts/setup-python.sh"; then
        echo -e "${RED}Error: Python environment setup failed${NC}"
        exit 1
    fi
else
    echo -e "${RED}Error: setup-python.sh not found at $SCRIPT_DIR/scripts/setup-python.sh${NC}"
    exit 1
fi

echo ""

# Get the Python command used by setup-python.sh
# Try to detect which Python was used
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo -e "${RED}Error: No Python interpreter found${NC}"
    exit 1
fi

# ============================================================
# Step 2: Install Additional Dependencies (MCP, click)
# ============================================================

echo -e "${BLUE}Step 2: Installing additional dependencies...${NC}"
echo ""

# Install MCP dependencies
echo "  Installing MCP dependencies..."
$PYTHON_CMD -m pip install mcp fastmcp > /dev/null 2>&1
echo -e "${GREEN}  ✓ MCP dependencies installed${NC}"

# Install click for CLI
$PYTHON_CMD -m pip install click > /dev/null 2>&1
echo -e "${GREEN}  ✓ click installed${NC}"

cd "$SCRIPT_DIR"
echo ""

# ============================================================
# Step 3: Verify Python Imports
# ============================================================

echo -e "${BLUE}Step 3: Verifying Python imports...${NC}"
echo ""

IMPORT_ERRORS=0

# Test framework import
if $PYTHON_CMD -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ framework imports OK${NC}"
else
    echo -e "${RED}  ✗ framework import failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

# Test aden_tools import
if $PYTHON_CMD -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ aden_tools imports OK${NC}"
else
    echo -e "${RED}  ✗ aden_tools import failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

# Test litellm import
if $PYTHON_CMD -c "import litellm" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ litellm imports OK${NC}"
else
    echo -e "${YELLOW}  ⚠ litellm import issues (may be OK)${NC}"
fi

# Test MCP server module
if $PYTHON_CMD -c "from framework.mcp import agent_builder_server" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ MCP server module OK${NC}"
else
    echo -e "${RED}  ✗ MCP server module failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

if [ $IMPORT_ERRORS -gt 0 ]; then
    echo ""
    echo -e "${RED}Error: $IMPORT_ERRORS import(s) failed. Please check the errors above.${NC}"
    exit 1
fi

echo ""

# ============================================================
# Step 4: Install Claude Code Skills (unless headless mode)
# ============================================================

if [ "$HEADLESS_MODE" = true ]; then
    echo -e "${BLUE}Step 4: Skipping Claude Code skills (headless mode)${NC}"
    echo ""
    echo -e "${YELLOW}  Note: To install Claude skills later, run:${NC}"
    echo -e "  ${BLUE}./quickstart.sh${NC} (without --headless flag)"
    echo ""
else
    echo -e "${BLUE}Step 4: Installing Claude Code skills...${NC}"
    echo ""

    # Check if .claude/skills exists in this repo
    if [ ! -d "$SCRIPT_DIR/.claude/skills" ]; then
        echo -e "${YELLOW}  ⚠ Skills directory not found at $SCRIPT_DIR/.claude/skills${NC}"
        echo -e "${YELLOW}  Skipping Claude skills installation${NC}"
    else
        # Create Claude skills directory if it doesn't exist
        if [ ! -d "$CLAUDE_SKILLS_DIR" ]; then
            echo "  Creating Claude skills directory: $CLAUDE_SKILLS_DIR"
            mkdir -p "$CLAUDE_SKILLS_DIR"
        fi

        # Function to install a skill
        install_skill() {
            local skill_name=$1
            local source_dir="$SCRIPT_DIR/.claude/skills/$skill_name"
            local target_dir="$CLAUDE_SKILLS_DIR/$skill_name"

            if [ ! -d "$source_dir" ]; then
                echo -e "${RED}  ✗ Skill not found: $skill_name${NC}"
                return 1
            fi

            # Check if skill already exists
            if [ -d "$target_dir" ]; then
                rm -rf "$target_dir"
            fi

            # Copy the skill
            cp -r "$source_dir" "$target_dir"
            echo -e "${GREEN}  ✓ Installed: $skill_name${NC}"
        }

        # Install all 5 agent-related skills
        install_skill "building-agents-core"
        install_skill "building-agents-construction"
        install_skill "building-agents-patterns"
        install_skill "testing-agent"
        install_skill "agent-workflow"
    fi

    echo ""
fi

# ============================================================
# Step 5: Verify MCP Configuration
# ============================================================

echo -e "${BLUE}Step 5: Verifying MCP configuration...${NC}"
echo ""

if [ -f "$SCRIPT_DIR/.mcp.json" ]; then
    echo -e "${GREEN}  ✓ .mcp.json found at project root${NC}"
    echo ""
    echo "  MCP servers configured:"
    $PYTHON_CMD -c "
import json
with open('$SCRIPT_DIR/.mcp.json') as f:
    config = json.load(f)
for name in config.get('mcpServers', {}):
    print(f'    - {name}')
" 2>/dev/null || echo "    (could not parse config)"
else
    echo -e "${YELLOW}  ⚠ No .mcp.json found at project root${NC}"
    echo "    Claude Code will not have access to MCP tools"
fi

echo ""

# ============================================================
# Step 6: Check API Key
# ============================================================

echo -e "${BLUE}Step 6: Checking API key...${NC}"
echo ""

# Check using CredentialManager (preferred)
API_KEY_AVAILABLE=$($PYTHON_CMD -c "
from aden_tools.credentials import CredentialManager
creds = CredentialManager()
print('yes' if creds.is_available('anthropic') else 'no')
" 2>/dev/null || echo "no")

if [ "$API_KEY_AVAILABLE" = "yes" ]; then
    echo -e "${GREEN}  ✓ ANTHROPIC_API_KEY is available${NC}"
elif [ -n "$ANTHROPIC_API_KEY" ]; then
    echo -e "${GREEN}  ✓ ANTHROPIC_API_KEY is set in environment${NC}"
else
    echo -e "${YELLOW}  ⚠ ANTHROPIC_API_KEY not found${NC}"
    echo ""
    echo "    For real agent testing, you'll need to set your API key:"
    echo "    ${BLUE}export ANTHROPIC_API_KEY='your-key-here'${NC}"
    echo ""
    echo "    Or add it to your .env file or credential manager."
fi

echo ""

# ============================================================
# Step 7: Success Summary
# ============================================================

echo "=================================================="
echo -e "${GREEN}  ✓ Setup Complete!${NC}"
echo "=================================================="
echo ""
echo "Installed Python packages:"
echo "  • framework (core agent runtime)"
echo "  • aden_tools (tools and MCP servers)"
echo "  • MCP dependencies (mcp, fastmcp)"
echo ""

if [ "$HEADLESS_MODE" = false ] && [ -d "$SCRIPT_DIR/.claude/skills" ]; then
    echo "Installed Claude Code skills:"
    echo "  • /building-agents-core        - Fundamental concepts"
    echo "  • /building-agents-construction - Step-by-step build guide"
    echo "  • /building-agents-patterns    - Best practices"
    echo "  • /testing-agent               - Test and validate agents"
    echo "  • /agent-workflow              - Complete workflow"
    echo ""
    echo "Usage:"
    echo "  1. Open Claude Code in this directory:"
    echo "     ${BLUE}cd $SCRIPT_DIR && claude${NC}"
    echo ""
    echo "  2. Build a new agent:"
    echo "     ${BLUE}/building-agents-construction${NC}"
    echo ""
    echo "  3. Test an existing agent:"
    echo "     ${BLUE}/testing-agent${NC}"
    echo ""
    echo "  4. Or use the complete workflow:"
    echo "     ${BLUE}/agent-workflow${NC}"
    echo ""
fi

echo "MCP Tools available (when running from this directory):"
echo "  • mcp__agent-builder__create_session"
echo "  • mcp__agent-builder__set_goal"
echo "  • mcp__agent-builder__add_node"
echo "  • mcp__agent-builder__run_tests"
echo "  • ... and more"
echo ""
echo "Documentation:"
if [ "$HEADLESS_MODE" = false ] && [ -d "$SCRIPT_DIR/.claude/skills" ]; then
    echo "  • Skills: $CLAUDE_SKILLS_DIR/"
fi
echo "  • Examples: $SCRIPT_DIR/exports/"
echo ""

if [ "$HEADLESS_MODE" = true ]; then
    echo -e "${YELLOW}Headless mode: Claude skills were not installed.${NC}"
    echo -e "Run ${BLUE}./quickstart.sh${NC} (without --headless) to install them."
    echo ""
fi
