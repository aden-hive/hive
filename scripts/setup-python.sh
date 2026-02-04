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

# Detect if running in virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo -e "${YELLOW}Note:${NC} Not running in a virtual environment"
    echo "  Recommended: Use a virtual environment to avoid conflicts"
    echo -e "  Create one with: ${BLUE}python3 -m venv .venv && source .venv/bin/activate${NC}"
    echo ""
else
    echo -e "${GREEN}✓${NC} Running in virtual environment: $(basename "$VIRTUAL_ENV")"
    echo ""
fi

# Check for Python
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Python Not Found${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Python is not installed on your system"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  Install Python 3.11+ using one of these methods:"
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS (Homebrew):"
        echo -e "    ${BLUE}brew install python@3.11${NC}"
        echo ""
        echo "  macOS (Official installer):"
        echo -e "    ${BLUE}https://www.python.org/downloads/${NC}"
    elif [[ "$OSTYPE" == "linux"* ]]; then
        echo "  Ubuntu/Debian:"
        echo -e "    ${BLUE}sudo apt update && sudo apt install python3.11${NC}"
        echo ""
        echo "  Fedora/RHEL:"
        echo -e "    ${BLUE}sudo dnf install python3.11${NC}"
    else
        echo "  Download from:"
        echo -e "    ${BLUE}https://www.python.org/downloads/${NC}"
    fi
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  Documentation: https://www.python.org/downloads/"
    echo ""
    exit 1
fi
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

echo -e "${BLUE}Detected Python:${NC} $PYTHON_VERSION"

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Python Version Too Old${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Python 3.11+ is required, but you have Python $PYTHON_VERSION"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  Upgrade Python using one of these methods:"
    echo ""
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS (Homebrew):"
        echo -e "    ${BLUE}brew install python@3.11${NC}"
        echo ""
        echo "  macOS (pyenv - recommended for managing multiple versions):"
        echo -e "    ${BLUE}brew install pyenv${NC}"
        echo -e "    ${BLUE}pyenv install 3.11.0${NC}"
        echo -e "    ${BLUE}pyenv global 3.11.0${NC}"
    elif [[ "$OSTYPE" == "linux"* ]]; then
        echo "  Ubuntu/Debian:"
        echo -e "    ${BLUE}sudo apt update && sudo apt install python3.11${NC}"
        echo ""
        echo "  Using pyenv (recommended for managing multiple versions):"
        echo -e "    ${BLUE}curl https://pyenv.run | bash${NC}"
        echo -e "    ${BLUE}pyenv install 3.11.0${NC}"
        echo -e "    ${BLUE}pyenv global 3.11.0${NC}"
    else
        echo "  Download from:"
        echo -e "    ${BLUE}https://www.python.org/downloads/${NC}"
    fi
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  This framework requires Python 3.11+ for compatibility with modern dependencies"
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  See installation guide: https://www.python.org/downloads/"
    echo ""
    exit 1
fi

if [ "$PYTHON_MINOR" -lt 11 ]; then
    echo -e "${YELLOW}Warning: Python 3.11+ is recommended for best compatibility${NC}"
    echo -e "${YELLOW}You have Python $PYTHON_VERSION which may work but is not officially supported${NC}"
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

# Check for pip
if ! $PYTHON_CMD -m pip --version &> /dev/null; then
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: pip Not Found${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  pip (Python package installer) is not available for Python $PYTHON_VERSION"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "  macOS:"
        echo -e "    ${BLUE}python3 -m ensurepip --upgrade${NC}"
        echo ""
        echo "  Or reinstall Python with Homebrew (includes pip):"
        echo -e "    ${BLUE}brew reinstall python@3.11${NC}"
    elif [[ "$OSTYPE" == "linux"* ]]; then
        echo "  Ubuntu/Debian:"
        echo -e "    ${BLUE}sudo apt install python3-pip${NC}"
        echo ""
        echo "  Fedora/RHEL:"
        echo -e "    ${BLUE}sudo dnf install python3-pip${NC}"
    else
        echo "  Run:"
        echo -e "    ${BLUE}python3 -m ensurepip --upgrade${NC}"
    fi
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  pip should be included with Python 3.11+, but it may need to be enabled"
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  See pip installation guide: https://pip.pypa.io/en/stable/installation/"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓${NC} pip detected"
echo ""

# Upgrade pip, setuptools, and wheel
echo "Upgrading pip, setuptools, and wheel..."
PIP_UPGRADE_OUTPUT=$(mktemp)
if ! $PYTHON_CMD -m pip install --upgrade pip setuptools wheel 2>"$PIP_UPGRADE_OUTPUT"; then
  PIP_ERROR=$(cat "$PIP_UPGRADE_OUTPUT")
  rm -f "$PIP_UPGRADE_OUTPUT"

  echo ""
  echo -e "${RED}========================================${NC}"
  echo -e "${RED}Setup Failed: Package Installation Error${NC}"
  echo -e "${RED}========================================${NC}"
  echo ""

  # Check for PEP 668 externally-managed-environment error
  if echo "$PIP_ERROR" | grep -q "externally-managed-environment\|This environment is externally managed"; then
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Your system Python is protected from modifications (PEP 668)"
    echo ""
    echo -e "${YELLOW}Quick fix (Recommended):${NC}"
    echo "  Create a virtual environment:"
    echo -e "    ${BLUE}python3 -m venv .venv${NC}"
    echo -e "    ${BLUE}source .venv/bin/activate${NC}"
    echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
    echo ""
    echo -e "${YELLOW}Alternative (Not recommended):${NC}"
    echo "  Use --break-system-packages flag (may cause conflicts):"
    echo -e "    ${BLUE}pip install --break-system-packages --upgrade pip setuptools wheel${NC}"
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  Modern Linux distributions prevent pip from modifying system Python packages"
    echo "  to avoid breaking system tools. Virtual environments are the recommended solution."
  elif echo "$PIP_ERROR" | grep -q "Permission denied\|PermissionError"; then
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Permission denied while trying to upgrade pip"
    echo ""
    echo -e "${YELLOW}Quick fix (Recommended):${NC}"
    echo "  Use a virtual environment:"
    echo -e "    ${BLUE}python3 -m venv .venv${NC}"
    echo -e "    ${BLUE}source .venv/bin/activate${NC}"
    echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
    echo ""
    echo -e "${YELLOW}Alternative:${NC}"
    echo "  Install to user directory:"
    echo -e "    ${BLUE}pip install --user --upgrade pip setuptools wheel${NC}"
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  You don't have write permissions to the Python installation directory"
  else
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Failed to upgrade pip, setuptools, and wheel"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  Try using a virtual environment:"
    echo -e "    ${BLUE}python3 -m venv .venv${NC}"
    echo -e "    ${BLUE}source .venv/bin/activate${NC}"
    echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
    echo ""
    echo -e "${YELLOW}Error details:${NC}"
    echo "$PIP_ERROR" | head -n 10
  fi
  echo ""
  echo -e "${YELLOW}Still stuck?${NC}"
  echo "  See Python virtual environments guide: https://docs.python.org/3/tutorial/venv.html"
  echo ""
  exit 1
fi
rm -f "$PIP_UPGRADE_OUTPUT"
echo -e "${GREEN}✓${NC} Core packages upgraded"
# Check for uv
if ! command -v uv &> /dev/null; then
    echo -e "${RED}Error: uv is not installed${NC}"
    echo "Please install uv from https://github.com/astral-sh/uv"
    exit 1
fi

echo -e "${GREEN}✓${NC} uv detected"
echo ""

# Smart Detection: Check for exports directory
if [ ! -d "$PROJECT_ROOT/exports" ]; then
    echo -e "${YELLOW}Note:${NC} exports/ directory not found"
    echo "  Creating exports/ directory for agent modules..."
    mkdir -p "$PROJECT_ROOT/exports"
    echo -e "${GREEN}✓${NC} Created exports/ directory"
    echo ""
fi

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
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Missing Project Files${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Required file 'pyproject.toml' not found in tools/ directory"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  This usually means the repository is incomplete. Try:"
    echo ""
    echo "  1. Re-clone the repository:"
    echo -e "    ${BLUE}git clone <repository-url>${NC}"
    echo -e "    ${BLUE}cd <repository-name>${NC}"
    echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
    echo ""
    echo "  2. Or if you already cloned, pull latest changes:"
    echo -e "    ${BLUE}git pull origin main${NC}"
    echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  The tools/ directory should contain pyproject.toml for package installation"
    echo "  If it's missing, the repository may be corrupted or incomplete"
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  Check if you're in the correct directory: $PROJECT_ROOT"
    echo "  Report this issue if the repository is freshly cloned"
    echo ""
    exit 1
fi
echo ""

# Smart Detection: Fix openai version compatibility with litellm
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
        echo "  Run manually: python -m playwright install chromium"
    fi
else
    echo -e "${YELLOW}⚠${NC} Playwright not found, skipping browser install"
fi
echo ""

# Fix openai version compatibility with litellm
echo "=================================================="
echo "Detecting and Fixing Package Compatibility"
echo "=================================================="
echo ""

TOOLS_PYTHON="$PROJECT_ROOT/tools/.venv/bin/python"

# Check openai version in tools venv
OPENAI_VERSION=$($TOOLS_PYTHON -c "import openai; print(openai.__version__)" 2>/dev/null || echo "not_installed")

if [ "$OPENAI_VERSION" = "not_installed" ]; then
    echo "Installing openai package..."
    INSTALL_OUTPUT=$(mktemp)
    if ! $PYTHON_CMD -m pip install "openai>=1.0.0" > "$INSTALL_OUTPUT" 2>&1; then
        INSTALL_ERROR=$(cat "$INSTALL_OUTPUT")
        rm -f "$INSTALL_OUTPUT"

        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Setup Failed: Dependency Installation Error${NC}"
        echo -e "${RED}========================================${NC}"
        echo ""
        echo -e "${YELLOW}What happened:${NC}"
        echo "  Failed to install openai package"
        echo ""

        # Smart detection of specific errors
        if echo "$INSTALL_ERROR" | grep -qi "network\|connection\|timeout\|unreachable"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Network connection issue detected. Try:"
            echo ""
            echo "  1. Check your internet connection"
            echo "  2. Try again with a different network"
            echo "  3. Use a different PyPI mirror:"
            echo -e "    ${BLUE}pip install --index-url https://pypi.org/simple openai>=1.0.0${NC}"
        elif echo "$INSTALL_ERROR" | grep -qi "conflict\|incompatible\|requires"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Dependency conflict detected. Try:"
            echo -e "    ${BLUE}pip install --upgrade openai>=1.0.0 --force-reinstall${NC}"
            echo ""
            echo -e "${YELLOW}Related issue:${NC}"
            echo "  See: https://github.com/BerriAI/litellm/issues (search for openai compatibility)"
        else
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Try installing in a clean virtual environment:"
            echo -e "    ${BLUE}python3 -m venv .venv${NC}"
            echo -e "    ${BLUE}source .venv/bin/activate${NC}"
            echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
        fi
        echo ""
        echo -e "${YELLOW}Error details:${NC}"
        echo "$INSTALL_ERROR" | head -n 15
        echo ""
        exit 1
    fi
    rm -f "$INSTALL_OUTPUT"
    uv pip install --python "$TOOLS_PYTHON" "openai>=1.0.0"
    echo -e "${GREEN}✓${NC} openai package installed"
elif [[ "$OPENAI_VERSION" =~ ^0\. ]]; then
    echo -e "${YELLOW}Detected Issue #450:${NC} Old openai version $OPENAI_VERSION (incompatible with litellm)"
    echo "Upgrading to openai 1.x+ for litellm compatibility..."
    UPGRADE_OUTPUT=$(mktemp)
    if ! $PYTHON_CMD -m pip install --upgrade "openai>=1.0.0" > "$UPGRADE_OUTPUT" 2>&1; then
        UPGRADE_ERROR=$(cat "$UPGRADE_OUTPUT")
        rm -f "$UPGRADE_OUTPUT"

        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Setup Failed: Dependency Conflict (Issue #450)${NC}"
        echo -e "${RED}========================================${NC}"
        echo ""
        echo -e "${YELLOW}What happened:${NC}"
        echo "  Cannot upgrade openai package due to conflicts"
        echo ""
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Force reinstall conflicting packages:"
        echo -e "    ${BLUE}pip uninstall -y openai litellm${NC}"
        echo -e "    ${BLUE}pip install 'openai>=1.0.0' litellm${NC}"
        echo ""
        echo -e "${YELLOW}Related issue:${NC}"
        echo "  GitHub: https://github.com/your-repo/issues/450"
        echo ""
        echo -e "${YELLOW}Error details:${NC}"
        echo "$UPGRADE_ERROR" | head -n 10
        echo ""
        exit 1
    fi
    rm -f "$UPGRADE_OUTPUT"
    OPENAI_VERSION=$($PYTHON_CMD -c "import openai; print(openai.__version__)" 2>/dev/null)
    echo -e "${GREEN}✓${NC} openai upgraded to $OPENAI_VERSION (Issue #450 resolved)"
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
    echo -e "${RED}✗${NC} framework package import failed"
    echo -e "${YELLOW}  Note: This may be OK if you don't need the framework${NC}"
fi

# Test aden_tools import with smart diagnostics
IMPORT_ERROR=$(mktemp)
if ! $PYTHON_CMD -c "import aden_tools; print('aden_tools OK')" > /dev/null 2>"$IMPORT_ERROR"; then
    IMPORT_ERROR_MSG=$(cat "$IMPORT_ERROR")
    rm -f "$IMPORT_ERROR"

    echo -e "${RED}✗${NC} aden_tools package import failed"
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Package Import Error${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  aden_tools package installed but cannot be imported"
    echo ""

    # Smart detection of common import errors
    if echo "$IMPORT_ERROR_MSG" | grep -qi "no module\|modulenotfounderror"; then
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Package may not be installed in the current Python environment"
        echo "  Try reinstalling:"
        echo -e "    ${BLUE}cd $PROJECT_ROOT/tools${NC}"
        echo -e "    ${BLUE}pip install -e . --force-reinstall${NC}"
    elif echo "$IMPORT_ERROR_MSG" | grep -qi "syntax\|invalid syntax"; then
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Python version mismatch detected"
        echo "  Verify you're using Python 3.11+:"
        echo -e "    ${BLUE}python --version${NC}"
    elif echo "$IMPORT_ERROR_MSG" | grep -qi "circular\|cyclic"; then
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Circular import detected in package"
        echo "  This may be a bug. Please report:"
        echo "  GitHub Issues: https://github.com/your-repo/issues"
    else
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Try a clean reinstall in a virtual environment:"
        echo -e "    ${BLUE}python3 -m venv .venv${NC}"
        echo -e "    ${BLUE}source .venv/bin/activate${NC}"
        echo -e "    ${BLUE}./scripts/setup-python.sh${NC}"
    fi

    echo ""
    echo -e "${YELLOW}Error details:${NC}"
    echo "$IMPORT_ERROR_MSG" | head -n 10
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  Report this issue: https://github.com/your-repo/issues"
    echo ""
    echo -e "${RED}✗${NC} core/.venv not found - venv creation may have failed${NC}"
    exit 1
else
    rm -f "$IMPORT_ERROR"
    echo -e "${GREEN}✓${NC} aden_tools package imports successfully"
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
