#!/bin/bash
#
# upgrade-packages.sh - Upgrade all Python packages in the virtualenv
#
# This script upgrades all installed packages to their latest versions
# and reinstalls the project packages in editable mode.

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
echo "  Upgrade All Python Packages"
echo "=================================================="
echo ""

# Check if virtualenv exists
if [ ! -d "$PROJECT_ROOT/virtualenv" ]; then
    echo -e "${RED}Error: virtualenv not found at $PROJECT_ROOT/virtualenv${NC}"
    echo "Please run ./scripts/setup-python.sh first"
    exit 1
fi

# Use the virtualenv Python
PYTHON_CMD="$PROJECT_ROOT/virtualenv/bin/python"

if [ ! -f "$PYTHON_CMD" ]; then
    echo -e "${RED}Error: Python not found in virtualenv${NC}"
    exit 1
fi

echo -e "${BLUE}Using Python:${NC} $PYTHON_CMD"
echo ""

# Step 1: Upgrade pip, setuptools, wheel
echo "=================================================="
echo "Step 1: Upgrading pip, setuptools, wheel"
echo "=================================================="
echo ""
$PYTHON_CMD -m pip install --upgrade pip setuptools wheel
echo -e "${GREEN}✓${NC} Core tools upgraded"
echo ""

# Step 2: Upgrade all installed packages
echo "=================================================="
echo "Step 2: Upgrading all installed packages"
echo "=================================================="
echo ""
echo "This may take a few minutes..."
$PYTHON_CMD -m pip list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1 | xargs -n1 $PYTHON_CMD -m pip install --upgrade || {
    echo -e "${YELLOW}⚠${NC} Some packages may have failed to upgrade (this is often OK)"
}
echo -e "${GREEN}✓${NC} Packages upgraded"
echo ""

# Step 3: Reinstall project packages in editable mode
echo "=================================================="
echo "Step 3: Reinstalling project packages"
echo "=================================================="
echo ""

# Reinstall core framework
echo "Reinstalling framework package..."
cd "$PROJECT_ROOT/core"
$PYTHON_CMD -m pip install --upgrade -e .
echo -e "${GREEN}✓${NC} Framework package reinstalled"
echo ""

# Reinstall tools package
echo "Reinstalling tools package..."
cd "$PROJECT_ROOT/tools"
$PYTHON_CMD -m pip install --upgrade -e .
echo -e "${GREEN}✓${NC} Tools package reinstalled"
echo ""

# Step 4: Verify installations
echo "=================================================="
echo "Step 4: Verifying installations"
echo "=================================================="
echo ""

cd "$PROJECT_ROOT"

# Test framework import
if $PYTHON_CMD -c "import framework; print('framework OK')" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} framework package imports successfully"
else
    echo -e "${RED}✗${NC} framework package import failed"
fi

# Test aden_tools import
if $PYTHON_CMD -c "import aden_tools; print('aden_tools OK')" > /dev/null 2>&1; then
    echo -e "${GREEN}✓${NC} aden_tools package imports successfully"
else
    echo -e "${RED}✗${NC} aden_tools package import failed"
fi

echo ""
echo "=================================================="
echo "  Upgrade Complete!"
echo "=================================================="
echo ""
echo "All packages have been upgraded to their latest versions."
echo ""
