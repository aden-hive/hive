#!/bin/bash
#
# setup-python.sh - Python Environment Setup for Aden Agent Framework
#
# DEPRECATED: Use ./quickstart.sh instead. It does everything this script
# does plus verifies MCP configuration, Claude Code skills, and API keys.
#
# This script is kept for CI/headless environments where the extra
# verification steps in quickstart.sh are not needed.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Python Version
REQUIRED_PYTHON_VERSION="3.11"

# Python version split into Major and Minor
IFS='.' read -r PYTHON_MAJOR_VERSION PYTHON_MINOR_VERSION <<< "$REQUIRED_PYTHON_VERSION"

# Available python interpreter (follows sequence)
POSSIBLE_PYTHONS=("python3" "python" "py")

# Default python interpreter (initialized)
PYTHON_CMD=()


echo ""
echo "=================================================="
echo "  Aden Agent Framework - Python Setup"
echo "=================================================="
echo ""
echo -e "${YELLOW}NOTE: Consider using ./quickstart.sh instead for a complete setup.${NC}"
echo ""

# Available Python interpreter
for cmd in "${POSSIBLE_PYTHONS[@]}"; do
    # Check for python interpreter
    if command -v "$cmd" >/dev/null 2>&1; then

        # Specific check for Windows 'py' launcher
        if [ "$cmd" = "py" ]; then
            CURRENT_CMD=(py -3)
        else
            CURRENT_CMD=("$cmd")
        fi

        # Check Python version
        if "${CURRENT_CMD[@]}" -c "import sys; sys.exit(0 if sys.version_info >= ($PYTHON_MAJOR_VERSION, $PYTHON_MINOR_VERSION) else 1)" >/dev/null 2>&1; then
            echo -e "${GREEN}✓${NC} interpreter detected: ${CURRENT_CMD[@]}"
            # Check for pip
            if "${CURRENT_CMD[@]}" -m pip --version >/dev/null 2>&1; then
                PYTHON_CMD=("${CURRENT_CMD[@]}")
                echo -e "${GREEN}✓${NC} pip detected"
                echo ""
                break
            else
                echo -e "${RED}✗${NC} pip not found"
                echo ""
            fi
        else
            echo -e "${RED}✗${NC} ${CURRENT_CMD[@]} not found"
            echo ""
        fi
    fi
done

# Display error message if python not found
if [ "${#PYTHON_CMD[@]}" -eq 0 ]; then
    echo -e "${RED}Error:${NC} No suitable Python interpreter found with pip installed."
    echo ""
    echo "Requirements:"
    echo "  • Python $PYTHON_MAJOR_VERSION.$PYTHON_MINOR_VERSION+"
    echo "  • pip installed"
    echo ""
    echo "Tried the following commands:"
    echo "  ${POSSIBLE_PYTHONS[*]}"
    echo ""
    echo "Please install Python from:"
    echo "  https://www.python.org/downloads/"
    exit 1
fi

# Display Python version
PYTHON_VERSION=$("${PYTHON_CMD[@]}" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo -e "${BLUE}Detected Python:${NC} $PYTHON_VERSION"
echo -e "${GREEN}✓${NC} Python version check passed"
echo ""

# Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "${RED}Error: uv is not installed${NC}"
    echo "Please install uv from https://github.com/astral-sh/uv"
    exit 1
fi

echo -e "${GREEN}✓${NC} uv detected"
echo ""

# Install core framework package
echo "=================================================="
echo "Installing Core Framework Package"
echo "=================================================="
echo ""
cd "$PROJECT_ROOT/core"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in core/.venv..."
    uv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
else
    echo -e "${GREEN}✓${NC} Virtual environment already exists"
fi
echo ""

if [ -f "pyproject.toml" ]; then
    echo "Installing framework from core/ (editable mode)..."
    CORE_PYTHON=".venv/bin/python"
    if uv pip install --python "$CORE_PYTHON" -e .; then
        echo -e "${GREEN}✓${NC} Framework package installed"
    else
        echo -e "${YELLOW}⚠${NC} Framework installation encountered issues (may be OK if already installed)"
    fi
else
    echo -e "${YELLOW}⚠${NC} No pyproject.toml found in core/, skipping framework installation"
fi
echo ""

# Install tools package
echo "=================================================="
echo "Installing Tools Package (aden_tools)"
echo "=================================================="
echo ""
cd "$PROJECT_ROOT/tools"

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in tools/.venv..."
    uv venv
    echo -e "${GREEN}✓${NC} Virtual environment created"
else
    echo -e "${GREEN}✓${NC} Virtual environment already exists"
fi
echo ""

if [ -f "pyproject.toml" ]; then
    echo "Installing aden_tools from tools/ (editable mode)..."
    TOOLS_PYTHON=".venv/bin/python"
    if uv pip install --python "$TOOLS_PYTHON" -e .; then
        echo -e "${GREEN}✓${NC} Tools package installed"
    else
        echo -e "${RED}✗${NC} Tools installation failed"
        exit 1
    fi
else
    echo -e "${RED}Error: No pyproject.toml found in tools/${NC}"
    exit 1
fi
echo ""

# Install Playwright browser for web scraping
echo "=================================================="
echo "Installing Playwright Browser"
echo "=================================================="
echo ""

if $PYTHON_CMD -c "import playwright" > /dev/null 2>&1; then
    echo "Installing Chromium browser for web scraping..."
    if $PYTHON_CMD -m playwright install chromium > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} Playwright Chromium installed"
    else
        echo -e "${YELLOW}⚠${NC} Playwright browser install failed (web_scrape tool may not work)"
        echo "  Run manually: uv run python -m playwright install chromium"
    fi
else
    echo -e "${YELLOW}⚠${NC} Playwright not found, skipping browser install"
fi
echo ""

# Fix openai version compatibility with litellm
echo "=================================================="
echo "Fixing Package Compatibility"
echo "=================================================="
echo ""

TOOLS_PYTHON="$PROJECT_ROOT/tools/.venv/bin/python"

# Check openai version in tools venv
OPENAI_VERSION=$($TOOLS_PYTHON -c "import openai; print(openai.__version__)" 2>/dev/null || echo "not_installed")

if [ "$OPENAI_VERSION" = "not_installed" ]; then
    echo "Installing openai package..."
    uv pip install --python "$TOOLS_PYTHON" "openai>=1.0.0"
    echo -e "${GREEN}✓${NC} openai package installed"
elif [[ "$OPENAI_VERSION" =~ ^0\. ]]; then
    echo -e "${YELLOW}Found old openai version: $OPENAI_VERSION${NC}"
    echo "Upgrading to openai 1.x+ for litellm compatibility..."
    uv pip install --python "$TOOLS_PYTHON" --upgrade "openai>=1.0.0"
    OPENAI_VERSION=$($TOOLS_PYTHON -c "import openai; print(openai.__version__)" 2>/dev/null)
    echo -e "${GREEN}✓${NC} openai upgraded to $OPENAI_VERSION"
else
    echo -e "${GREEN}✓${NC} openai $OPENAI_VERSION is compatible"
fi
echo ""

# Ensure exports directory exists
echo "=================================================="
echo "Checking Directory Structure"
echo "=================================================="
echo ""

if [ ! -d "$PROJECT_ROOT/exports" ]; then
    echo "Creating exports directory..."
    mkdir -p "$PROJECT_ROOT/exports"
    echo "# Agent Exports" > "$PROJECT_ROOT/exports/README.md"
    echo "" >> "$PROJECT_ROOT/exports/README.md"
    echo "This directory is the default location for generated agent packages." >> "$PROJECT_ROOT/exports/README.md"
    echo -e "${GREEN}✓${NC} Created exports directory"
else
    echo -e "${GREEN}✓${NC} exports directory exists"
fi
echo ""

# Verify installations
echo "=================================================="
echo "Verifying Installation"
echo "=================================================="
echo ""

cd "$PROJECT_ROOT"

# Test framework import using core venv
CORE_PYTHON="$PROJECT_ROOT/core/.venv/bin/python"
if [ -f "$CORE_PYTHON" ]; then
    if $CORE_PYTHON -c "import framework; print('framework OK')" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} framework package imports successfully"
    else
        echo -e "${RED}✗${NC} framework package import failed"
        echo -e "${YELLOW}  Note: This may be OK if you don't need the framework${NC}"
    fi
else
    echo -e "${RED}✗${NC} core/.venv not found - venv creation may have failed${NC}"
    exit 1
fi

# Test aden_tools import using tools venv
TOOLS_PYTHON="$PROJECT_ROOT/tools/.venv/bin/python"
if [ -f "$TOOLS_PYTHON" ]; then
    if $TOOLS_PYTHON -c "import aden_tools; print('aden_tools OK')" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC} aden_tools package imports successfully"
    else
        echo -e "${RED}✗${NC} aden_tools package import failed"
        exit 1
    fi
else
    echo -e "${RED}✗${NC} tools/.venv not found - venv creation may have failed${NC}"
    exit 1
fi

# Test litellm + openai compatibility using tools venv
if $TOOLS_PYTHON -c "import litellm; print('litellm OK')" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} litellm package imports successfully"
else
    echo -e "${YELLOW}⚠${NC} litellm import had issues (may be OK if not using LLM features)"
fi

echo ""

# Print agent commands
echo "=================================================="
echo "  Setup Complete!"
echo "=================================================="
echo ""
echo "Python packages installed:"
echo "  • framework (core agent runtime)"
echo "  • aden_tools (tools and MCP servers)"
echo "  • All dependencies and compatibility fixes applied"
echo ""
echo "To run agents, use:"
echo ""
echo "  ${BLUE}# From project root:${NC}"
echo "  PYTHONPATH=exports uv run python -m agent_name validate"
echo "  PYTHONPATH=exports uv run python -m agent_name info"
echo "  PYTHONPATH=exports uv run python -m agent_name run --input '{...}'"
echo ""
echo "Available commands for your new agent:"
echo "  PYTHONPATH=exports uv run python -m support_ticket_agent validate"
echo "  PYTHONPATH=exports uv run python -m support_ticket_agent info"
echo "  PYTHONPATH=exports uv run python -m support_ticket_agent run --input '{\"ticket_content\":\"...\",\"customer_id\":\"...\",\"ticket_id\":\"...\"}'"
echo ""
echo "To build new agents, use Claude Code skills:"
echo "  • /building-agents - Build a new agent"
echo "  • /testing-agent   - Test an existing agent"
echo ""
echo "Documentation: ${PROJECT_ROOT}/README.md"
echo "Agent Examples: ${PROJECT_ROOT}/exports/"
echo ""
