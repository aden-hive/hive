#!/bin/bash
#
# quickstart.sh - Interactive onboarding for Aden Agent Framework
#
# An interactive setup wizard that:
# 1. Installs Python dependencies
# 2. Installs Playwright browser for web scraping
# 3. Helps configure LLM API keys
# 4. Verifies everything works
#

set -e

# Detect Bash version for compatibility
BASH_MAJOR_VERSION="${BASH_VERSINFO[0]}"
USE_ASSOC_ARRAYS=false
if [ "$BASH_MAJOR_VERSION" -ge 4 ]; then
    USE_ASSOC_ARRAYS=true
fi
echo "[debug] Bash version: ${BASH_VERSION}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Helper function for prompts
prompt_yes_no() {
    local prompt="$1"
    local default="${2:-y}"
    local response

    if [ "$default" = "y" ]; then
        prompt="$prompt [Y/n] "
    else
        prompt="$prompt [y/N] "
    fi

    read -r -p "$prompt" response
    response="${response:-$default}"
    [[ "$response" =~ ^[Yy] ]]
}

# Helper function for choice prompts
prompt_choice() {
    local prompt="$1"
    shift
    local options=("$@")
    local i=1

    echo ""
    echo -e "${BOLD}$prompt${NC}"
    for opt in "${options[@]}"; do
        echo -e "  ${CYAN}$i)${NC} $opt"
        i=$((i + 1))
    done
    echo ""

    local choice
    while true; do
        read -r -p "Enter choice (1-${#options[@]}): " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            PROMPT_CHOICE=$((choice - 1))
            return 0
        fi
        echo -e "${RED}Invalid choice. Please enter 1-${#options[@]}${NC}"
    done
}

clear
echo ""
echo -e "${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}"
echo ""
echo -e "${BOLD}          A D E N   H I V E${NC}"
echo ""
echo -e "${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}"
echo ""
echo -e "${DIM}     Goal-driven AI agent framework${NC}"
echo ""
echo "This wizard will help you set up everything you need"
echo "to build and run goal-driven AI agents."
echo ""

if ! prompt_yes_no "Ready to begin?"; then
    echo ""
    echo "No problem! Run this script again when you're ready."
    exit 0
fi

echo ""

# ============================================================
# Step 1: Check Python
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 1: Checking Python...${NC}"
echo ""

# Check for Python
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo -e "${RED}Python is not installed.${NC}"
    echo ""
    echo "Please install Python 3.11+ from https://python.org"
    echo "Then run this script again."
    exit 1
fi

# Prefer a Python >= 3.11 if multiple are installed (common on macOS).
PYTHON_CMD=""
for CANDIDATE in python3.11 python3.12 python3.13 python3 python; do
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

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo -e "${RED}Python 3.11+ is required (found $PYTHON_VERSION)${NC}"
    echo ""
    echo "Please upgrade your Python installation and run this script again."
    exit 1
fi

echo -e "${GREEN}⬢${NC} Python $PYTHON_VERSION"
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

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 2: Installing packages...${NC}"
echo ""

echo -e "${DIM}This may take a minute...${NC}"
echo ""

# Install framework package from core/
echo -n "  Installing framework... "
cd "$SCRIPT_DIR/core"

if [ -f "pyproject.toml" ]; then
    if uv sync > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ framework package installed${NC}"
    else
        echo -e "${YELLOW}  ⚠ framework installation had issues (may be OK)${NC}"
    fi
else
    echo -e "${RED}failed (no pyproject.toml)${NC}"
    exit 1
fi

# Install aden_tools package from tools/
echo -n "  Installing tools... "
cd "$SCRIPT_DIR/tools"

if [ -f "pyproject.toml" ]; then
    if uv sync > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ aden_tools package installed${NC}"
    else
        echo -e "${RED}  ✗ aden_tools installation failed${NC}"
        exit 1
    fi
else
    echo -e "${RED}failed${NC}"
    exit 1
fi

# Install Playwright browser
echo -n "  Installing Playwright browser... "
if $PYTHON_CMD -c "import playwright" > /dev/null 2>&1; then
    if $PYTHON_CMD -m playwright install chromium > /dev/null 2>&1; then
        echo -e "${GREEN}ok${NC}"
    else
        echo -e "${YELLOW}⏭${NC}"
    fi
else
    echo -e "${YELLOW}⏭${NC}"
fi

cd "$SCRIPT_DIR"
echo ""
echo -e "${GREEN}⬢${NC} All packages installed"
echo ""

# ============================================================
# Step 3: Configure LLM API Key
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 3: Configuring LLM provider...${NC}"
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

# Provider configuration - use associative arrays (Bash 4+) or indexed arrays (Bash 3.2)
if [ "$USE_ASSOC_ARRAYS" = true ]; then
    # Bash 4+ - use associative arrays (cleaner and more efficient)
    declare -A PROVIDER_NAMES=(
        ["ANTHROPIC_API_KEY"]="Anthropic (Claude)"
        ["OPENAI_API_KEY"]="OpenAI (GPT)"
        ["GEMINI_API_KEY"]="Google Gemini"
        ["GOOGLE_API_KEY"]="Google AI"
        ["GROQ_API_KEY"]="Groq"
        ["CEREBRAS_API_KEY"]="Cerebras"
        ["MISTRAL_API_KEY"]="Mistral"
        ["TOGETHER_API_KEY"]="Together AI"
        ["DEEPSEEK_API_KEY"]="DeepSeek"
    )

    declare -A PROVIDER_IDS=(
        ["ANTHROPIC_API_KEY"]="anthropic"
        ["OPENAI_API_KEY"]="openai"
        ["GEMINI_API_KEY"]="gemini"
        ["GOOGLE_API_KEY"]="google"
        ["GROQ_API_KEY"]="groq"
        ["CEREBRAS_API_KEY"]="cerebras"
        ["MISTRAL_API_KEY"]="mistral"
        ["TOGETHER_API_KEY"]="together"
        ["DEEPSEEK_API_KEY"]="deepseek"
    )

    declare -A DEFAULT_MODELS=(
        ["anthropic"]="claude-sonnet-4-5-20250929"
        ["openai"]="gpt-4o"
        ["gemini"]="gemini-3.0-flash-preview"
        ["groq"]="moonshotai/kimi-k2-instruct-0905"
        ["cerebras"]="zai-glm-4.7"
        ["mistral"]="mistral-large-latest"
        ["together_ai"]="meta-llama/Llama-3.3-70B-Instruct-Turbo"
        ["deepseek"]="deepseek-chat"
    )

    # Helper functions for Bash 4+
    get_provider_name() {
        echo "${PROVIDER_NAMES[$1]}"
    }

    get_provider_id() {
        echo "${PROVIDER_IDS[$1]}"
    }

    get_default_model() {
        echo "${DEFAULT_MODELS[$1]}"
    }
else
    # Bash 3.2 - use parallel indexed arrays
    PROVIDER_ENV_VARS=(ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY GROQ_API_KEY CEREBRAS_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY DEEPSEEK_API_KEY)
    PROVIDER_DISPLAY_NAMES=("Anthropic (Claude)" "OpenAI (GPT)" "Google Gemini" "Google AI" "Groq" "Cerebras" "Mistral" "Together AI" "DeepSeek")
    PROVIDER_ID_LIST=(anthropic openai gemini google groq cerebras mistral together deepseek)

    # Default models by provider id (parallel arrays)
    MODEL_PROVIDER_IDS=(anthropic openai gemini groq cerebras mistral together_ai deepseek)
    MODEL_DEFAULTS=("claude-sonnet-4-5-20250929" "gpt-4o" "gemini-3.0-flash-preview" "moonshotai/kimi-k2-instruct-0905" "zai-glm-4.7" "mistral-large-latest" "meta-llama/Llama-3.3-70B-Instruct-Turbo" "deepseek-chat")

    # Helper: get provider display name for an env var
    get_provider_name() {
        local env_var="$1"
        local i=0
        while [ $i -lt ${#PROVIDER_ENV_VARS[@]} ]; do
            if [ "${PROVIDER_ENV_VARS[$i]}" = "$env_var" ]; then
                echo "${PROVIDER_DISPLAY_NAMES[$i]}"
                return
            fi
            i=$((i + 1))
        done
    }

    # Helper: get provider id for an env var
    get_provider_id() {
        local env_var="$1"
        local i=0
        while [ $i -lt ${#PROVIDER_ENV_VARS[@]} ]; do
            if [ "${PROVIDER_ENV_VARS[$i]}" = "$env_var" ]; then
                echo "${PROVIDER_ID_LIST[$i]}"
                return
            fi
            i=$((i + 1))
        done
    }

    # Helper: get default model for a provider id
    get_default_model() {
        local provider_id="$1"
        local i=0
        while [ $i -lt ${#MODEL_PROVIDER_IDS[@]} ]; do
            if [ "${MODEL_PROVIDER_IDS[$i]}" = "$provider_id" ]; then
                echo "${MODEL_DEFAULTS[$i]}"
                return
            fi
            i=$((i + 1))
        done
    }
fi

# Configuration directory
HIVE_CONFIG_DIR="$HOME/.hive"
HIVE_CONFIG_FILE="$HIVE_CONFIG_DIR/configuration.json"

# Function to save configuration
save_configuration() {
    local provider_id="$1"
    local env_var="$2"
    local model
    model="$(get_default_model "$provider_id")"

    mkdir -p "$HIVE_CONFIG_DIR"

    $PYTHON_CMD -c "
import json
config = {
    'llm': {
        'provider': '$provider_id',
        'model': '$model',
        'api_key_env_var': '$env_var'
    },
    'created_at': '$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")'
}
with open('$HIVE_CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
print(json.dumps(config, indent=2))
" 2>/dev/null
}

# Check for .env files (temporarily disable set -e for robustness on Bash 3.2)
set +e
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env" 2>/dev/null
    set +a
fi

if [ -f "$HOME/.env" ]; then
    set -a
    source "$HOME/.env" 2>/dev/null
    set +a
fi
set -e

# Find all available API keys
FOUND_PROVIDERS=()      # Display names for UI
FOUND_ENV_VARS=()       # Corresponding env var names
SELECTED_PROVIDER_ID="" # Will hold the chosen provider ID
SELECTED_ENV_VAR=""     # Will hold the chosen env var

if [ "$USE_ASSOC_ARRAYS" = true ]; then
    # Bash 4+ - iterate over associative array keys
    for env_var in "${!PROVIDER_NAMES[@]}"; do
        value="${!env_var}"
        if [ -n "$value" ]; then
            FOUND_PROVIDERS+=("$(get_provider_name "$env_var")")
            FOUND_ENV_VARS+=("$env_var")
        fi
    done
else
    # Bash 3.2 - iterate over indexed array
    for env_var in "${PROVIDER_ENV_VARS[@]}"; do
        value="${!env_var}"
        if [ -n "$value" ]; then
            FOUND_PROVIDERS+=("$(get_provider_name "$env_var")")
            FOUND_ENV_VARS+=("$env_var")
        fi
    done
fi

if [ ${#FOUND_PROVIDERS[@]} -gt 0 ]; then
    echo "Found API keys:"
    echo ""
    for provider in "${FOUND_PROVIDERS[@]}"; do
        echo -e "  ${GREEN}⬢${NC} $provider"
    done
    echo ""

    if [ ${#FOUND_PROVIDERS[@]} -eq 1 ]; then
        # Only one provider found, use it automatically
        if prompt_yes_no "Use this key?"; then
            SELECTED_ENV_VAR="${FOUND_ENV_VARS[0]}"
            SELECTED_PROVIDER_ID="$(get_provider_id "$SELECTED_ENV_VAR")"

            echo ""
            echo -e "${GREEN}⬢${NC} Using ${FOUND_PROVIDERS[0]}"
        fi
    else
        # Multiple providers found, let user pick one
        echo -e "${BOLD}Select your default LLM provider:${NC}"
        echo ""

        # Build choice menu from found providers
        i=1
        for provider in "${FOUND_PROVIDERS[@]}"; do
            echo -e "  ${CYAN}$i)${NC} $provider"
            i=$((i + 1))
        done
        echo ""

        while true; do
            read -r -p "Enter choice (1-${#FOUND_PROVIDERS[@]}): " choice
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#FOUND_PROVIDERS[@]}" ]; then
                idx=$((choice - 1))
                SELECTED_ENV_VAR="${FOUND_ENV_VARS[$idx]}"
                SELECTED_PROVIDER_ID="$(get_provider_id "$SELECTED_ENV_VAR")"

                echo ""
                echo -e "${GREEN}⬢${NC} Selected: ${FOUND_PROVIDERS[$idx]}"
                break
            fi
            echo -e "${RED}Invalid choice. Please enter 1-${#FOUND_PROVIDERS[@]}${NC}"
        done
    fi
fi

if [ -z "$SELECTED_PROVIDER_ID" ]; then
    echo "No API keys found. Let's configure one."
    echo ""

    prompt_choice "Select your LLM provider:" \
        "Anthropic (Claude) - Recommended" \
        "OpenAI (GPT)" \
        "Google Gemini - Free tier available" \
        "Groq - Fast, free tier" \
        "Cerebras - Fast, free tier" \
        "Skip for now"
     choice=$PROMPT_CHOICE

    case $choice in
        0)
            SELECTED_ENV_VAR="ANTHROPIC_API_KEY"
            SELECTED_PROVIDER_ID="anthropic"
            PROVIDER_NAME="Anthropic"
            SIGNUP_URL="https://console.anthropic.com/settings/keys"
            ;;
        1)
            SELECTED_ENV_VAR="OPENAI_API_KEY"
            SELECTED_PROVIDER_ID="openai"
            PROVIDER_NAME="OpenAI"
            SIGNUP_URL="https://platform.openai.com/api-keys"
            ;;
        2)
            SELECTED_ENV_VAR="GEMINI_API_KEY"
            SELECTED_PROVIDER_ID="gemini"
            PROVIDER_NAME="Google Gemini"
            SIGNUP_URL="https://aistudio.google.com/apikey"
            ;;
        3)
            SELECTED_ENV_VAR="GROQ_API_KEY"
            SELECTED_PROVIDER_ID="groq"
            PROVIDER_NAME="Groq"
            SIGNUP_URL="https://console.groq.com/keys"
            ;;
        4)
            SELECTED_ENV_VAR="CEREBRAS_API_KEY"
            SELECTED_PROVIDER_ID="cerebras"
            PROVIDER_NAME="Cerebras"
            SIGNUP_URL="https://cloud.cerebras.ai/"
            ;;
        5)
            echo ""
            echo -e "${YELLOW}Skipped.${NC} An LLM API key is required to test and use worker agents."
            echo -e "Add your API key later by running:"
            echo ""
            echo -e "  ${CYAN}echo 'ANTHROPIC_API_KEY=your-key' >> .env${NC}"
            echo ""
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
            ;;
    esac

    if [ -n "$SELECTED_ENV_VAR" ] && [ -z "${!SELECTED_ENV_VAR}" ]; then
        echo ""
        echo -e "Get your API key from: ${CYAN}$SIGNUP_URL${NC}"
        echo ""
        read -r -p "Paste your $PROVIDER_NAME API key (or press Enter to skip): " API_KEY

        if [ -n "$API_KEY" ]; then
            # Save to .env
            echo "" >> "$SCRIPT_DIR/.env"
            echo "$SELECTED_ENV_VAR=$API_KEY" >> "$SCRIPT_DIR/.env"
            export "$SELECTED_ENV_VAR=$API_KEY"
            echo ""
            echo -e "${GREEN}⬢${NC} API key saved to .env"
        else
            echo ""
            echo -e "${YELLOW}Skipped.${NC} Add your API key to .env when ready."
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
        fi
    fi
fi

# Save configuration if a provider was selected
if [ -n "$SELECTED_PROVIDER_ID" ]; then
    echo ""
    echo -n "  Saving configuration... "
    save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" > /dev/null
    echo -e "${GREEN}⬢${NC}"
    echo -e "  ${DIM}~/.hive/configuration.json${NC}"
fi

echo ""

# ============================================================
# Step 4: Verify Setup
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 4: Verifying installation...${NC}"
echo ""

ERRORS=0

# Test imports
echo -n "  ⬡ framework... "
if $CORE_PYTHON -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo -n "  ⬡ aden_tools... "
if $TOOLS_PYTHON -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo -n "  ⬡ litellm... "
if $CORE_PYTHON -c "import litellm" > /dev/null 2>&1 || $TOOLS_PYTHON -c "import litellm" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${YELLOW}--${NC}"
fi

echo -n "  ⬡ MCP config... "
if [ -f "$SCRIPT_DIR/.mcp.json" ]; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${YELLOW}--${NC}"
fi

echo -n "  ⬡ skills... "
if [ -d "$SCRIPT_DIR/.claude/skills" ]; then
    SKILL_COUNT=$(ls -1d "$SCRIPT_DIR/.claude/skills"/*/ 2>/dev/null | wc -l)
    echo -e "${GREEN}${SKILL_COUNT} found${NC}"
else
    echo -e "${YELLOW}--${NC}"
fi

echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}Setup failed with $ERRORS error(s).${NC}"
    echo "Please check the errors above and try again."
    exit 1
fi

# ============================================================
# Success!
# ============================================================

clear
echo ""
echo -e "${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}"
echo ""
echo -e "${GREEN}${BOLD}        ADEN HIVE — READY${NC}"
echo ""
echo -e "${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}${DIM}⬡${NC}${GREEN}⬢${NC}"
echo ""
echo -e "Your environment is configured for building AI agents."
echo ""

# Show configured provider
if [ -n "$SELECTED_PROVIDER_ID" ]; then
    SELECTED_MODEL="$(get_default_model "$SELECTED_PROVIDER_ID")"
    echo -e "${BOLD}Default LLM:${NC}"
    echo -e "  ${CYAN}$SELECTED_PROVIDER_ID${NC} → ${DIM}$SELECTED_MODEL${NC}"
    echo ""
fi

echo -e "${BOLD}Quick Start:${NC}"
echo ""
echo -e "  1. Open Claude Code in this directory:"
echo -e "     ${CYAN}claude${NC}"
echo ""
echo -e "  2. Build a new agent:"
echo -e "     ${CYAN}/agent-workflow${NC}"
echo ""
echo -e "  3. Test an existing agent:"
echo -e "     ${CYAN}/testing-agent${NC}"
echo ""
echo -e "${BOLD}Skills:${NC}"
if [ -d "$SCRIPT_DIR/.claude/skills" ]; then
    for skill_dir in "$SCRIPT_DIR/.claude/skills"/*/; do
        skill_name=$(basename "$skill_dir")
        echo -e "  ⬡ ${CYAN}/$skill_name${NC}"
    done
fi
echo ""
echo -e "${BOLD}Examples:${NC} ${CYAN}exports/${NC}"
echo ""
echo -e "${DIM}Run ./quickstart.sh again to reconfigure.${NC}"
echo ""
