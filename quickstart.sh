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

# ============================================================
# Step 1: Check Python Prerequisites
# ============================================================

echo -e "${BLUE}Step 1: Checking Python prerequisites...${NC}"
echo ""

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

# Use python3 if available, otherwise python
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$($PYTHON_CMD -c 'import sys; print(sys.version_info.minor)')

echo -e "  Detected Python: ${GREEN}$PYTHON_VERSION${NC}"

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
    echo -e "${YELLOW}  Warning: Python 3.11+ is recommended for best compatibility${NC}"
fi

echo -e "${GREEN}  ✓ Python version OK${NC}"
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

echo -e "${GREEN}  ✓ pip detected${NC}"
echo ""

# ============================================================
# Step 2: Install Python Packages
# ============================================================

echo -e "${BLUE}Step 2: Installing Python packages...${NC}"
echo ""

# Upgrade pip, setuptools, and wheel
echo "  Upgrading pip, setuptools, wheel..."
$PYTHON_CMD -m pip install --upgrade pip setuptools wheel > /dev/null 2>&1
echo -e "${GREEN}  ✓ Core tools upgraded${NC}"
echo ""

# Smart Detection: Check for exports directory
if [ ! -d "$SCRIPT_DIR/exports" ]; then
    echo -e "${YELLOW}Note:${NC} exports/ directory not found"
    echo "  Creating exports/ directory for agent modules..."
    mkdir -p "$SCRIPT_DIR/exports"
    echo -e "${GREEN}  ✓ Created exports/ directory${NC}"
    echo ""
fi

# Install framework package from core/
echo "  Installing framework package from core/..."
cd "$SCRIPT_DIR/core"
if [ -f "pyproject.toml" ]; then
    INSTALL_OUTPUT=$(mktemp)
    if ! $PYTHON_CMD -m pip install -e . > "$INSTALL_OUTPUT" 2>&1; then
        INSTALL_ERROR=$(cat "$INSTALL_OUTPUT")
        rm -f "$INSTALL_OUTPUT"

        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Setup Failed: Framework Installation Error${NC}"
        echo -e "${RED}========================================${NC}"
        echo ""
        echo -e "${YELLOW}What happened:${NC}"
        echo "  Failed to install framework package from core/"
        echo ""

        # Smart detection of specific errors
        if echo "$INSTALL_ERROR" | grep -qi "network\|connection\|timeout"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Network issue detected. Check your internet connection and try again"
        elif echo "$INSTALL_ERROR" | grep -qi "permission denied\|permissionerror"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Permission error detected. Try:"
            echo -e "    ${BLUE}chmod -R u+w $SCRIPT_DIR/core${NC}"
            echo "  Or use a virtual environment:"
            echo -e "    ${BLUE}python3 -m venv .venv && source .venv/bin/activate${NC}"
        elif echo "$INSTALL_ERROR" | grep -qi "conflict\|incompatible"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Dependency conflict. Try in a clean virtual environment:"
            echo -e "    ${BLUE}python3 -m venv .venv${NC}"
            echo -e "    ${BLUE}source .venv/bin/activate${NC}"
            echo -e "    ${BLUE}./quickstart.sh${NC}"
        else
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Try reinstalling with verbose output:"
            echo -e "    ${BLUE}cd $SCRIPT_DIR/core && pip install -e . -v${NC}"
        fi
        echo ""
        echo -e "${YELLOW}Error details:${NC}"
        echo "$INSTALL_ERROR" | head -n 15
        echo ""
        exit 1
    fi
    rm -f "$INSTALL_OUTPUT"
    echo -e "${GREEN}  ✓ framework package installed${NC}"
else
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Missing pyproject.toml${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  No pyproject.toml found in core/ directory"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  1. Verify you cloned the full repository:"
    echo -e "    ${BLUE}ls -la $SCRIPT_DIR/core/pyproject.toml${NC}"
    echo "  2. Re-clone if necessary:"
    echo -e "    ${BLUE}git clone <repository-url>${NC}"
    echo ""
    exit 1
fi

# Install aden_tools package from tools/
echo "  Installing aden_tools package from tools/..."
cd "$SCRIPT_DIR/tools"
if [ -f "pyproject.toml" ]; then
    INSTALL_OUTPUT=$(mktemp)
    if ! $PYTHON_CMD -m pip install -e . > "$INSTALL_OUTPUT" 2>&1; then
        INSTALL_ERROR=$(cat "$INSTALL_OUTPUT")
        rm -f "$INSTALL_OUTPUT"

        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Setup Failed: Tools Package Installation Error${NC}"
        echo -e "${RED}========================================${NC}"
        echo ""
        echo -e "${YELLOW}What happened:${NC}"
        echo "  Failed to install aden_tools package from tools/"
        echo ""

        # Smart detection
        if echo "$INSTALL_ERROR" | grep -qi "network\|connection\|timeout"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Network issue. Check internet connection and retry"
        elif echo "$INSTALL_ERROR" | grep -qi "permission"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Use a virtual environment to avoid permission issues:"
            echo -e "    ${BLUE}python3 -m venv .venv && source .venv/bin/activate${NC}"
        else
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Try verbose installation:"
            echo -e "    ${BLUE}cd $SCRIPT_DIR/tools && pip install -e . -v${NC}"
        fi
        echo ""
        echo -e "${YELLOW}Error details:${NC}"
        echo "$INSTALL_ERROR" | head -n 15
        echo ""
        exit 1
    fi
    rm -f "$INSTALL_OUTPUT"
    echo -e "${GREEN}  ✓ aden_tools package installed${NC}"
else
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Missing pyproject.toml${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  No pyproject.toml found in tools/ directory"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  Verify repository structure:"
    echo -e "    ${BLUE}ls -la $SCRIPT_DIR/tools/pyproject.toml${NC}"
    echo ""
    exit 1
fi

# Install MCP dependencies
echo "  Installing MCP dependencies..."
INSTALL_OUTPUT=$(mktemp)
if ! $PYTHON_CMD -m pip install mcp fastmcp > "$INSTALL_OUTPUT" 2>&1; then
    INSTALL_ERROR=$(cat "$INSTALL_OUTPUT")
    rm -f "$INSTALL_OUTPUT"

    echo ""
    echo -e "${YELLOW}Warning:${NC} MCP dependencies installation failed"
    echo "  This may not be critical for basic agent functionality"
    echo ""

    # Check if it's a network issue
    if echo "$INSTALL_ERROR" | grep -qi "network\|connection\|timeout"; then
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Network issue. Retry when internet is stable"
    fi
    echo ""
else
    rm -f "$INSTALL_OUTPUT"
    echo -e "${GREEN}  ✓ MCP dependencies installed${NC}"
fi

# Smart Detection: Fix openai version compatibility with litellm (Issue #450)
OPENAI_VERSION=$($PYTHON_CMD -c "import openai; print(openai.__version__)" 2>/dev/null || echo "not_installed")
if [ "$OPENAI_VERSION" = "not_installed" ]; then
    echo "  Installing openai package..."
    INSTALL_OUTPUT=$(mktemp)
    if ! $PYTHON_CMD -m pip install "openai>=1.0.0" > "$INSTALL_OUTPUT" 2>&1; then
        INSTALL_ERROR=$(cat "$INSTALL_OUTPUT")
        rm -f "$INSTALL_OUTPUT"

        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Setup Failed: openai Installation Error${NC}"
        echo -e "${RED}========================================${NC}"
        echo ""
        echo -e "${YELLOW}What happened:${NC}"
        echo "  Failed to install openai package"
        echo ""

        if echo "$INSTALL_ERROR" | grep -qi "network\|connection\|timeout"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Network issue. Check connection and retry"
        elif echo "$INSTALL_ERROR" | grep -qi "conflict\|incompatible"; then
            echo -e "${YELLOW}Quick fix:${NC}"
            echo "  Dependency conflict. Use clean virtual environment:"
            echo -e "    ${BLUE}python3 -m venv .venv && source .venv/bin/activate${NC}"
            echo ""
            echo -e "${YELLOW}Related issue:${NC}"
            echo "  GitHub: https://github.com/your-repo/issues/450"
        fi
        echo ""
        echo -e "${YELLOW}Error details:${NC}"
        echo "$INSTALL_ERROR" | head -n 10
        echo ""
        exit 1
    fi
    rm -f "$INSTALL_OUTPUT"
    echo -e "${GREEN}  ✓ openai installed${NC}"
elif [[ "$OPENAI_VERSION" =~ ^0\. ]]; then
    echo -e "${YELLOW}  Detected Issue #450:${NC} Old openai $OPENAI_VERSION (incompatible with litellm)"
    echo "  Upgrading to openai 1.x+..."
    UPGRADE_OUTPUT=$(mktemp)
    if ! $PYTHON_CMD -m pip install --upgrade "openai>=1.0.0" > "$UPGRADE_OUTPUT" 2>&1; then
        UPGRADE_ERROR=$(cat "$UPGRADE_OUTPUT")
        rm -f "$UPGRADE_OUTPUT"

        echo ""
        echo -e "${RED}========================================${NC}"
        echo -e "${RED}Setup Failed: openai Upgrade Error (Issue #450)${NC}"
        echo -e "${RED}========================================${NC}"
        echo ""
        echo -e "${YELLOW}What happened:${NC}"
        echo "  Cannot upgrade openai due to dependency conflicts"
        echo ""
        echo -e "${YELLOW}Quick fix:${NC}"
        echo "  Force reinstall:"
        echo -e "    ${BLUE}pip uninstall -y openai litellm${NC}"
        echo -e "    ${BLUE}pip install 'openai>=1.0.0' litellm${NC}"
        echo ""
        echo -e "${YELLOW}Related issue:${NC}"
        echo "  GitHub: https://github.com/your-repo/issues/450"
        echo ""
        exit 1
    fi
    rm -f "$UPGRADE_OUTPUT"
    OPENAI_VERSION=$($PYTHON_CMD -c "import openai; print(openai.__version__)" 2>/dev/null)
    echo -e "${GREEN}  ✓ openai upgraded to $OPENAI_VERSION (Issue #450 resolved)${NC}"
else
    echo -e "${GREEN}  ✓ openai $OPENAI_VERSION is compatible${NC}"
fi

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

# Test framework import with smart diagnostics
IMPORT_ERROR=$(mktemp)
if $PYTHON_CMD -c "import framework" > /dev/null 2>"$IMPORT_ERROR"; then
    echo -e "${GREEN}  ✓ framework imports OK${NC}"
else
    IMPORT_ERROR_MSG=$(cat "$IMPORT_ERROR")
    echo -e "${RED}  ✗ framework import failed${NC}"
    echo ""

    # Smart detection of import issues
    if echo "$IMPORT_ERROR_MSG" | grep -qi "no module"; then
        echo -e "${YELLOW}  Quick fix:${NC} Reinstall framework package:"
        echo -e "    ${BLUE}cd $SCRIPT_DIR/core && pip install -e .${NC}"
    elif echo "$IMPORT_ERROR_MSG" | grep -qi "syntax"; then
        echo -e "${YELLOW}  Quick fix:${NC} Python version mismatch. Verify Python 3.11+:"
        echo -e "    ${BLUE}python --version${NC}"
    fi
    echo ""
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi
rm -f "$IMPORT_ERROR"

# Test aden_tools import with smart diagnostics
IMPORT_ERROR=$(mktemp)
if $PYTHON_CMD -c "import aden_tools" > /dev/null 2>"$IMPORT_ERROR"; then
    echo -e "${GREEN}  ✓ aden_tools imports OK${NC}"
else
    IMPORT_ERROR_MSG=$(cat "$IMPORT_ERROR")
    echo -e "${RED}  ✗ aden_tools import failed${NC}"
    echo ""

    if echo "$IMPORT_ERROR_MSG" | grep -qi "no module"; then
        echo -e "${YELLOW}  Quick fix:${NC} Reinstall aden_tools package:"
        echo -e "    ${BLUE}cd $SCRIPT_DIR/tools && pip install -e .${NC}"
    fi
    echo ""
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi
rm -f "$IMPORT_ERROR"

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
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Package Import Errors${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  $IMPORT_ERRORS Python package(s) failed to import after installation"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  Try reinstalling in a clean virtual environment:"
    echo ""
    echo -e "    ${BLUE}python3 -m venv .venv${NC}"
    echo -e "    ${BLUE}source .venv/bin/activate${NC}"
    echo -e "    ${BLUE}./quickstart.sh${NC}"
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  Package conflicts or incomplete installations can prevent imports"
    echo "  Using a fresh virtual environment often resolves these issues"
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  Check the error messages above for specific package issues"
    echo "  Try installing packages individually to identify the problem"
    echo ""
    exit 1
fi

echo ""

# ============================================================
# Step 4: Install Claude Code Skills
# ============================================================

echo -e "${BLUE}Step 4: Installing Claude Code skills...${NC}"
echo ""

# Check if .claude/skills exists in this repo
if [ ! -d "$SCRIPT_DIR/.claude/skills" ]; then
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}Setup Failed: Missing Skills Directory${NC}"
    echo -e "${RED}========================================${NC}"
    echo ""
    echo -e "${YELLOW}What happened:${NC}"
    echo "  Skills directory not found at: $SCRIPT_DIR/.claude/skills"
    echo ""
    echo -e "${YELLOW}Quick fix:${NC}"
    echo "  The repository may be incomplete. Try:"
    echo ""
    echo "  1. Re-clone the repository:"
    echo -e "    ${BLUE}git clone <repository-url>${NC}"
    echo -e "    ${BLUE}cd <repository-name>${NC}"
    echo -e "    ${BLUE}./quickstart.sh${NC}"
    echo ""
    echo "  2. Or pull latest changes:"
    echo -e "    ${BLUE}git pull origin main${NC}"
    echo -e "    ${BLUE}./quickstart.sh${NC}"
    echo ""
    echo -e "${YELLOW}Why this happened:${NC}"
    echo "  The .claude/skills directory contains Claude Code skill definitions"
    echo "  If it's missing, the repository clone may have failed or be outdated"
    echo ""
    echo -e "${YELLOW}Still stuck?${NC}"
    echo "  Verify you're in the correct directory: $SCRIPT_DIR"
    echo "  You can skip skills installation by using ./scripts/setup-python.sh instead"
    echo ""
    exit 1
fi

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
echo "MCP Tools available (when running from this directory):"
echo "  • mcp__agent-builder__create_session"
echo "  • mcp__agent-builder__set_goal"
echo "  • mcp__agent-builder__add_node"
echo "  • mcp__agent-builder__run_tests"
echo "  • ... and more"
echo ""
echo "Documentation:"
echo "  • Skills: $CLAUDE_SKILLS_DIR/"
echo "  • Examples: $SCRIPT_DIR/exports/"
echo ""
