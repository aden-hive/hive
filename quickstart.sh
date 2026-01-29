#!/bin/bash
#
# quickstart.sh - Complete setup for Aden Agent Framework skills
#
# This script:
# 1. Installs Python dependencies (framework, aden_tools, MCP)
# 2. Installs Claude Code skills for building and testing agents
# 3. Verifies the setup is ready to use
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

# Claude Code skills directory
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"

echo ""
echo "=================================================="
echo "  Aden Agent Framework - Complete Setup"
echo "=================================================="
echo ""

# ============================================================
# Step 1: Check Python Prerequisites
# ============================================================

echo -e "${BLUE}Step 1: Checking Python prerequisites...${NC}"
echo ""

# Check for Python
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python is not installed.${NC}"
    echo "Please install Python 3.11+ from https://python.org"
    exit 1
fi

# Prefer a Python >= 3.11 if multiple are installed (common on macOS).
PYTHON_CMD=""
for CANDIDATE in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$CANDIDATE" &> /dev/null; then
        PYTHON_MAJOR=$("$CANDIDATE" -c 'import sys; print(sys.version_info.major)')
        PYTHON_MINOR=$("$CANDIDATE" -c 'import sys; print(sys.version_info.minor)')
        if [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
            PYTHON_CMD="$CANDIDATE"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    # Fall back to python3/python just for a helpful detected version in the error message.
    PYTHON_CMD="python3"
    if ! command -v python3 &> /dev/null; then
        PYTHON_CMD="python"
    fi
fi

# Check Python version (for logging/error messages)
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

echo -e "  Detected Python: ${GREEN}$PYTHON_VERSION${NC} (${PYTHON_CMD})"

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}Error: Python 3.11+ is required (found $PYTHON_VERSION via ${PYTHON_CMD})${NC}"
    echo "Please upgrade your Python installation or ensure python3.11+ is on your PATH"
    exit 1
fi

echo -e "${GREEN}  ✓ Python version OK${NC}"
echo ""

# Check for pip
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo -e "${RED}Error: pip is not installed${NC}"
    echo "Please install pip for Python $PYTHON_VERSION"
    exit 1
fi

echo -e "${GREEN}  ✓ pip detected${NC}"
echo ""

# Check for uv (install automatically if missing)
if ! command -v uv &> /dev/null; then
    echo -e "${YELLOW}  uv not found. Installing...${NC}"
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}Error: curl is not installed (needed to install uv)${NC}"
        echo "Please install curl or install uv manually from https://astral.sh/uv/"
        exit 1
    fi

    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

    if ! command -v uv &> /dev/null; then
        echo -e "${RED}Error: uv installation failed${NC}"
        echo "Please install uv manually from https://astral.sh/uv/"
        exit 1
    fi
    echo -e "${GREEN}  ✓ uv installed successfully${NC}"
fi

UV_VERSION=$(uv --version)
echo -e "${GREEN}  ✓ uv detected: $UV_VERSION${NC}"
echo ""

# ============================================================
# Step 2: Install Python Packages
# ============================================================

echo -e "${BLUE}Step 2: Installing Python packages...${NC}"
echo ""

# Install framework package from core/
echo "  Installing framework package from core/..."
cd "$SCRIPT_DIR/core"

if [ -f "pyproject.toml" ]; then
    uv sync > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ framework package installed${NC}"
    else
        echo -e "${YELLOW}  ⚠ framework installation had issues (may be OK)${NC}"
    fi
else
    echo -e "${RED}  ✗ No pyproject.toml in core/${NC}"
    exit 1
fi

# Install aden_tools package from tools/
echo "  Installing aden_tools package from tools/..."
cd "$SCRIPT_DIR/tools"

if [ -f "pyproject.toml" ]; then
    uv sync > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}  ✓ aden_tools package installed${NC}"
    else
        echo -e "${RED}  ✗ aden_tools installation failed${NC}"
        exit 1
    fi
else
    echo -e "${RED}  ✗ No pyproject.toml in tools/${NC}"
    exit 1
fi

# Install MCP dependencies (in tools venv)
echo "  Installing MCP dependencies..."
TOOLS_PYTHON="$SCRIPT_DIR/tools/.venv/bin/python"
uv pip install --python "$TOOLS_PYTHON" mcp fastmcp > /dev/null 2>&1
echo -e "${GREEN}  ✓ MCP dependencies installed${NC}"

# Fix openai version compatibility (in tools venv)
TOOLS_PYTHON="$SCRIPT_DIR/tools/.venv/bin/python"
OPENAI_VERSION=$($TOOLS_PYTHON -c "import openai; print(openai.__version__)" 2>/dev/null || echo "not_installed")
if [ "$OPENAI_VERSION" = "not_installed" ]; then
    echo "  Installing openai package..."
    uv pip install --python "$TOOLS_PYTHON" "openai>=1.0.0" > /dev/null 2>&1
    echo -e "${GREEN}  ✓ openai installed${NC}"
elif [[ "$OPENAI_VERSION" =~ ^0\. ]]; then
    echo "  Upgrading openai to 1.x+ for litellm compatibility..."
    uv pip install --python "$TOOLS_PYTHON" --upgrade "openai>=1.0.0" > /dev/null 2>&1
    echo -e "${GREEN}  ✓ openai upgraded${NC}"
else
    echo -e "${GREEN}  ✓ openai $OPENAI_VERSION is compatible${NC}"
fi

# Install click for CLI (in tools venv)
TOOLS_PYTHON="$SCRIPT_DIR/tools/.venv/bin/python"
uv pip install --python "$TOOLS_PYTHON" click > /dev/null 2>&1
echo -e "${GREEN}  ✓ click installed${NC}"

cd "$SCRIPT_DIR"
echo ""

# ============================================================
# Step 3: Verify Python Imports
# ============================================================

echo -e "${BLUE}Step 3: Verifying Python imports...${NC}"
echo ""

IMPORT_ERRORS=0

# Test imports using their respective venvs
CORE_PYTHON="$SCRIPT_DIR/core/.venv/bin/python"
TOOLS_PYTHON="$SCRIPT_DIR/tools/.venv/bin/python"

# Test framework import (from core venv)
if [ -f "$CORE_PYTHON" ] && $CORE_PYTHON -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ framework imports OK${NC}"
else
    echo -e "${RED}  ✗ framework import failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

# Test aden_tools import (from tools venv)
if [ -f "$TOOLS_PYTHON" ] && $TOOLS_PYTHON -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ aden_tools imports OK${NC}"
else
    echo -e "${RED}  ✗ aden_tools import failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

# Test litellm import (from core venv)
if [ -f "$CORE_PYTHON" ] && $CORE_PYTHON -c "import litellm" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ litellm imports OK (core)${NC}"
else
    echo -e "${YELLOW}  ⚠ litellm import issues in core (may be OK)${NC}"
fi

# Test litellm import (from tools venv)
if [ -f "$TOOLS_PYTHON" ] && $TOOLS_PYTHON -c "import litellm" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ litellm imports OK (tools)${NC}"
else
    echo -e "${YELLOW}  ⚠ litellm import issues in tools (may be OK)${NC}"
fi

# Test MCP server module (from core venv)
if [ -f "$CORE_PYTHON" ] && $CORE_PYTHON -c "from framework.mcp import agent_builder_server" > /dev/null 2>&1; then
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
# Step 4: Verify Claude Code Skills
# ============================================================

echo -e "${BLUE}Step 4: Verifying Claude Code skills...${NC}"
echo ""

# Check if .claude/skills exists in this repo
if [ ! -d "$SCRIPT_DIR/.claude/skills" ]; then
    echo -e "${RED}Error: Skills directory not found at $SCRIPT_DIR/.claude/skills${NC}"
    exit 1
fi

# Verify all 5 agent-related skills exist locally
SKILLS=("building-agents-core" "building-agents-construction" "building-agents-patterns" "testing-agent" "agent-workflow")
for skill in "${SKILLS[@]}"; do
    if [ -d "$SCRIPT_DIR/.claude/skills/$skill" ]; then
        echo -e "${GREEN}  ✓ Found: $skill${NC}"
    else
        echo -e "${RED}  ✗ Not found: $skill${NC}"
        exit 1
    fi
done

echo ""

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
echo "Available Claude Code skills (in project directory):"
echo "  • /building-agents-core        - Fundamental concepts"
echo "  • /building-agents-construction - Step-by-step build guide"
echo "  • /building-agents-patterns    - Best practices"
echo "  • /testing-agent               - Test and validate agents"
echo "  • /agent-workflow              - Complete workflow"
echo ""
echo "Usage:"
echo "  1. Open Claude Code in this directory:"
echo "     cd $SCRIPT_DIR && claude"
echo ""
echo "  2. Build a new agent:"
echo "     /building-agents-construction"
echo ""
echo "  3. Test an existing agent:"
echo "     /testing-agent"
echo ""
echo "  4. Or use the complete workflow:"
echo "     /agent-workflow"
echo ""
echo "MCP Tools available (when running from this directory):"
echo "  • mcp__agent-builder__create_session"
echo "  • mcp__agent-builder__set_goal"
echo "  • mcp__agent-builder__add_node"
echo "  • mcp__agent-builder__run_tests"
echo "  • ... and more"
echo ""
echo "Documentation:"
echo "  • Skills: $SCRIPT_DIR/.claude/skills/"
echo "  • Examples: $SCRIPT_DIR/exports/"
echo ""
