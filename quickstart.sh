#!/usr/bin/env bash
#
# quickstart.sh - Interactive onboarding for Aden Agent Framework
#
# =============================================================================
# MAINTAINER UPDATE
# -----------------------------------------------------------------------------
# Updated by: Shashank Rajput
# Date: 2026-02-02
#
# Why this change:
# - Editable installs (pip -e) on WSL + Windows-mounted paths (/mnt/*)
#   often hang or fail due to build isolation + filesystem latency.
# - Python 3.12 requires explicit build backend (hatchling) for PEP 517/660.
#
# What changed:
# - Explicit, deterministic virtualenv creation (python -m venv)
# - Fully quoted, space-safe paths
# - Explicit installation of hatchling + build
# - Disabled pip build isolation for editable installs
# - No reliance on uv or implicit side-effects
#
# Result:
# - Fast, reliable onboarding on WSL, Linux, and macOS
# - Script-only install (no manual recovery steps)
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Environment hardening (WSL + pip)
# -----------------------------------------------------------------------------
export PIP_NO_BUILD_ISOLATION=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_CACHE_DIR=1

# -----------------------------------------------------------------------------
# Colors
# -----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# -----------------------------------------------------------------------------
# Resolve script directory (SPACE SAFE)
# -----------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -----------------------------------------------------------------------------
# Prompt helper
# -----------------------------------------------------------------------------
prompt_yes_no() {
  read -r -p "$1 [Y/n] " reply
  [[ "${reply:-Y}" =~ ^[Yy]$ ]]
}

# -----------------------------------------------------------------------------
# Banner
# -----------------------------------------------------------------------------
clear
echo -e "${BOLD}A D E N   H I V E${NC}"
echo -e "${DIM}Goal-driven AI agent framework${NC}"
echo ""

prompt_yes_no "Ready to begin?" || exit 0

# -----------------------------------------------------------------------------
# Step 1: Python check
# -----------------------------------------------------------------------------
echo -e "\n${BLUE}${BOLD}Step 1: Checking Python...${NC}"

PYTHON_CMD=""
for C in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$C" >/dev/null 2>&1; then
    MAJOR=$("$C" -c 'import sys; print(sys.version_info.major)')
    MINOR=$("$C" -c 'import sys; print(sys.version_info.minor)')
    if [[ "$MAJOR" -eq 3 && "$MINOR" -ge 11 ]]; then
      PYTHON_CMD="$C"
      break
    fi
  fi
done

if [[ -z "$PYTHON_CMD" ]]; then
  echo -e "${RED}Python 3.11+ is required${NC}"
  exit 1
fi

echo -e "${GREEN}✓ $($PYTHON_CMD --version)${NC}"

# -----------------------------------------------------------------------------
# Step 2: Create virtual environments
# -----------------------------------------------------------------------------
echo -e "\n${BLUE}${BOLD}Step 2: Creating virtual environments...${NC}"

CORE_VENV="${SCRIPT_DIR}/core/.venv"
TOOLS_VENV="${SCRIPT_DIR}/tools/.venv"

[[ -d "$CORE_VENV" ]] || "$PYTHON_CMD" -m venv "$CORE_VENV"
[[ -d "$TOOLS_VENV" ]] || "$PYTHON_CMD" -m venv "$TOOLS_VENV"

CORE_PY="${CORE_VENV}/bin/python"
TOOLS_PY="${TOOLS_VENV}/bin/python"

echo -e "${GREEN}✓ core venv ready${NC}"
echo -e "${GREEN}✓ tools venv ready${NC}"

# -----------------------------------------------------------------------------
# Step 3: Install packages (FAST + SAFE)
# -----------------------------------------------------------------------------
echo -e "\n${BLUE}${BOLD}Step 3: Installing packages...${NC}"

# Upgrade base tooling + editable backend deps
"$CORE_PY"  -m pip install --upgrade pip setuptools wheel hatchling build editables >/dev/null
"$TOOLS_PY" -m pip install --upgrade pip setuptools wheel hatchling build editables >/dev/null

echo -n "Installing framework (core)... "
"$CORE_PY" -m pip install -e "${SCRIPT_DIR}/core" --no-build-isolation >/dev/null
echo -e "${GREEN}ok${NC}"

echo -n "Installing tools (aden_tools)... "
"$TOOLS_PY" -m pip install -e "${SCRIPT_DIR}/tools" --no-build-isolation >/dev/null
echo -e "${GREEN}ok${NC}"

echo -n "Installing shared dependencies... "
"$CORE_PY"  -m pip install "openai>=1.0.0" litellm click mcp fastmcp >/dev/null
"$TOOLS_PY" -m pip install "openai>=1.0.0" click mcp fastmcp >/dev/null
echo -e "${GREEN}ok${NC}"


# -----------------------------------------------------------------------------
# Step 4: Verify imports
# -----------------------------------------------------------------------------
echo -e "\n${BLUE}${BOLD}Step 4: Verifying installation...${NC}"

"$CORE_PY"  -c "import framework, litellm"
"$TOOLS_PY" -c "import aden_tools"

echo -e "${GREEN}✓ All imports OK${NC}"

# -----------------------------------------------------------------------------
# Contributor mode
# -----------------------------------------------------------------------------
echo -e "\n${CYAN}Contributor Mode:${NC}"
echo "No API keys required."
echo "Run agents in mock mode:"
echo ""
echo "  PYTHONPATH=core:exports \\"
echo "  core/.venv/bin/python -m framework.cli run --mock --goal \"Test\""
echo ""

# -----------------------------------------------------------------------------
# Success
# -----------------------------------------------------------------------------
echo -e "${GREEN}${BOLD}ADEN HIVE — READY${NC}"
echo ""
echo "Next:"
echo "  source core/.venv/bin/activate"
echo "  PYTHONPATH=core:exports python -m framework.cli --help"
echo ""
