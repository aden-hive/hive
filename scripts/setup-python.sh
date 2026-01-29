#!/bin/bash
#
# setup-python.sh - Python Environment Setup for Aden Agent Framework
#
# This script sets up the Python environment with all required packages
# for building and running goal-driven agents.
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

echo ""
echo "=================================================="
echo "  Aden Agent Framework - Python Setup"
echo "=================================================="
echo ""

# Check for Python, honoring $PYTHON even if it's not on PATH
if [ -n "$PYTHON" ]; then
    if [ ! -x "$PYTHON" ] && ! command -v "$PYTHON" &> /dev/null; then
        echo -e "${RED}Error: PYTHON is set to '$PYTHON' but it was not found or not executable.${NC}"
        echo "Example: PYTHON=/opt/python3.12/bin/python3.12 ./scripts/setup-python.sh"
        exit 1
    fi
elif ! command -v python &> /dev/null \
   && ! command -v python3 &> /dev/null \
   && ! command -v python3.11 &> /dev/null \
   && ! command -v python3.12 &> /dev/null; then
    echo -e "${RED}Error: Python is not installed.${NC}"
    echo "Please install Python 3.11+ (recommended 3.12) from https://python.org"
    exit 1
fi

# Choose Python interpreter
# Priority:
#  1) $PYTHON env var override (e.g., PYTHON=python3.11)
#  2) python3.12 if available
#  3) python3.11 if available
#  4) python3
#  5) python
PYTHON_CMD="${PYTHON:-}"

if [ -n "$PYTHON_CMD" ]; then
    if [ -x "$PYTHON_CMD" ]; then
        : # absolute / explicit path provided and executable
    elif command -v "$PYTHON_CMD" &> /dev/null; then
        : # found on PATH
    else
        echo -e "${RED}Error: PYTHON is set to '$PYTHON_CMD' but it was not found in PATH or as an absolute path.${NC}"
        echo "Example: PYTHON=/opt/python3.12/bin/python3.12 ./scripts/setup-python.sh"
        exit 1
    fi
elif command -v python3.12 &> /dev/null; then
    PYTHON_CMD="python3.12"
elif command -v python3.11 &> /dev/null; then
    PYTHON_CMD="python3.11"
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

echo -e "${BLUE}Detected Python:${NC} $PYTHON_VERSION (binary: ${PYTHON_CMD})"

# Require 3.11+
if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}Error: Python 3.11+ is required (found $PYTHON_VERSION via '$PYTHON_CMD')${NC}"
    echo ""
    echo "Fix options (Linux/macOS/WSL):"
    echo "  • Ubuntu/Debian/Pop!_OS/WSL:"
    echo "      sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-dev"
    echo "  • Fedora:"
    echo "      sudo dnf install -y python3.11 python3.11-devel"
    echo "  • Arch/Manjaro:"
    echo "      sudo pacman -S python"
    echo "  • macOS (Homebrew):"
    echo "      brew install python@3.11"
    echo ""
    echo "Then re-run with an explicit interpreter if needed:"
    echo "  PYTHON=python3.11 ./scripts/setup-python.sh"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓${NC} Python version check passed"
echo ""

# Check for pip
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo -e "${RED}Error: pip is not installed${NC}"
    echo "Please install pip for Python $PYTHON_VERSION"
    exit 1
fi

echo -e "${GREEN}✓${NC} pip detected"
echo ""

# Upgrade pip, setuptools, and wheel
echo "Upgrading pip, setuptools, and wheel..."
if ! $PYTHON_CMD -m pip install --upgrade pip setuptools wheel; then
  echo "Error: Failed to upgrade pip. Please check your python/venv configuration."
  exit 1
fi
echo -e "${GREEN}✓${NC} Core packages upgraded"
echo ""

# Install core framework package
echo "=================================================="
echo "Installing Core Framework Package"
echo "=================================================="
echo ""
cd "$PROJECT_ROOT/core"

if [ -f "pyproject.toml" ]; then
    echo "Installing framework from core/ (editable mode)..."
    $PYTHON_CMD -m pip install -e . > /dev/null 2>&1
    if [ $? -eq 0 ]; then
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

if [ -f "pyproject.toml" ]; then
    echo "Installing aden_tools from tools/ (editable mode)..."
    $PYTHON_CMD -m pip install -e . > /dev/null 2>&1
    if [ $? -eq 0 ]; then
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

# Fix openai version compatibility with litellm
echo "=================================================="
echo "Fixing Package Compatibility"
echo "=================================================="
echo ""

# Check openai version
OPENAI_VERSION=$($PYTHON_CMD -c "import openai; print(openai.__version__)" 2>/dev/null || echo "not_installed")

if [ "$OPENAI_VERSION" = "not_installed" ]; then
    echo "Installing openai package..."
    $PYTHON_CMD -m pip install "openai>=1.0.0" > /dev/null 2>&1
    echo -e "${GREEN}✓${NC} openai package installed"
elif [[ "$OPENAI_VERSION" =~ ^0\. ]]; then
    echo -e "${YELLOW}Found old openai version: $OPENAI_VERSION${NC}"
    echo "Upgrading to openai 1.x+ for litellm compatibility..."
    $PYTHON_CMD -m pip install --upgrade "openai>=1.0.0" > /dev/null 2>&1
    OPENAI_VERSION=$($PYTHON_CMD -c "import openai; print(openai.__version__)" 2>/dev/null)
    echo -e "${GREEN}✓${NC} openai upgraded to $OPENAI_VERSION"
else
    echo -e "${GREEN}✓${NC} openai $OPENAI_VERSION is compatible"
fi
echo ""

# Verify installations
echo "=================================================="
echo "Verifying Installation"
echo "=================================================="
echo ""

cd "$PROJECT_ROOT"

# Test framework import
if $PYTHON_CMD -c "import framework; print('framework OK')" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} framework package imports successfully"
else
    echo -e "${RED}✗${NC} framework package import failed"
    echo -e "${YELLOW}  Note: This may be OK if you don't need the framework${NC}"
fi

# Test aden_tools import
if $PYTHON_CMD -c "import aden_tools; print('aden_tools OK')" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} aden_tools package imports successfully"
else
    echo -e "${RED}✗${NC} aden_tools package import failed"
    exit 1
fi

# Test litellm + openai compatibility
if $PYTHON_CMD -c "import litellm; print('litellm OK')" > /dev/null 2>&1; then
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
echo "  PYTHONPATH=core:exports ${PYTHON_CMD} -m agent_name validate"
echo "  PYTHONPATH=core:exports ${PYTHON_CMD} -m agent_name info"
echo "  PYTHONPATH=core:exports ${PYTHON_CMD} -m agent_name run --input '{...}'"
echo ""
echo "Available commands for your new agent:"
echo "  PYTHONPATH=core:exports ${PYTHON_CMD} -m support_ticket_agent validate"
echo "  PYTHONPATH=core:exports ${PYTHON_CMD} -m support_ticket_agent info"
echo "  PYTHONPATH=core:exports ${PYTHON_CMD} -m support_ticket_agent run --input '{\"ticket_content\":\"...\",\"customer_id\":\"...\",\"ticket_id\":\"...\"}'"
echo ""
echo "To build new agents, use Claude Code skills:"
echo "  • /building-agents - Build a new agent"
echo "  • /testing-agent   - Test an existing agent"
echo ""
echo "Documentation: ${PROJECT_ROOT}/README.md"
echo "Agent Examples: ${PROJECT_ROOT}/exports/"
echo ""
