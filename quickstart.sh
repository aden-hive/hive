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
        ((i++))
    done
    echo ""

    local choice
    while true; do
        read -r -p "Enter choice (1-${#options[@]}): " choice
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
            return $((choice - 1))
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

# Use python3 if available, otherwise python
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

# Check Python version
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

# ============================================================
# Step 2: Install Python Packages
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 2: Installing packages...${NC}"
echo ""

echo -e "${DIM}This may take a minute...${NC}"
echo ""

# Upgrade pip, setuptools, and wheel
echo -n "  Upgrading pip... "
$PYTHON_CMD -m pip install --upgrade pip setuptools wheel > /dev/null 2>&1
echo -e "${GREEN}ok${NC}"

# Install framework package from core/
echo -n "  Installing framework... "
cd "$SCRIPT_DIR/core"
if [ -f "pyproject.toml" ]; then
    $PYTHON_CMD -m pip install -e . > /dev/null 2>&1
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed (no pyproject.toml)${NC}"
    exit 1
fi

# Install aden_tools package from tools/
echo -n "  Installing tools... "
cd "$SCRIPT_DIR/tools"
if [ -f "pyproject.toml" ]; then
    $PYTHON_CMD -m pip install -e . > /dev/null 2>&1
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    exit 1
fi

# Install MCP dependencies
echo -n "  Installing MCP... "
$PYTHON_CMD -m pip install mcp fastmcp > /dev/null 2>&1
echo -e "${GREEN}ok${NC}"

# Fix openai version compatibility
echo -n "  Checking openai... "
$PYTHON_CMD -m pip install "openai>=1.0.0" > /dev/null 2>&1
echo -e "${GREEN}ok${NC}"

# Install click for CLI
echo -n "  Installing CLI tools... "
$PYTHON_CMD -m pip install click > /dev/null 2>&1
echo -e "${GREEN}ok${NC}"

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
echo ""

# Define supported providers (env_var -> display_name, litellm_provider, default_model)
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

# Configuration directory
HIVE_CONFIG_DIR="$HOME/.hive"
HIVE_CONFIG_FILE="$HIVE_CONFIG_DIR/configuration.json"

# Function to save configuration
save_configuration() {
    local provider_id="$1"
    local env_var="$2"
    local model="${DEFAULT_MODELS[$provider_id]}"

    mkdir -p "$HIVE_CONFIG_DIR"

    $PYTHON_CMD -c "
import json
config = {
    'llm': {
        'provider': '$provider_id',
        'model': '$model',
        'api_key_env_var': '$env_var'
    },
    'created_at': '$(date -Iseconds)'
}
with open('$HIVE_CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
print(json.dumps(config, indent=2))
" 2>/dev/null
}

# Check for .env files
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env" 2>/dev/null || true
    set +a
fi

if [ -f "$HOME/.env" ]; then
    set -a
    source "$HOME/.env" 2>/dev/null || true
    set +a
fi

# Find all available API keys
FOUND_PROVIDERS=()      # Display names for UI
FOUND_ENV_VARS=()       # Corresponding env var names
SELECTED_PROVIDER_ID="" # Will hold the chosen provider ID
SELECTED_ENV_VAR=""     # Will hold the chosen env var

for env_var in "${!PROVIDER_NAMES[@]}"; do
    value="${!env_var}"
    if [ -n "$value" ]; then
        FOUND_PROVIDERS+=("${PROVIDER_NAMES[$env_var]}")
        FOUND_ENV_VARS+=("$env_var")
    fi
done

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
            SELECTED_PROVIDER_ID="${PROVIDER_IDS[$SELECTED_ENV_VAR]}"

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
            ((i++))
        done
        echo ""

        while true; do
            read -r -p "Enter choice (1-${#FOUND_PROVIDERS[@]}): " choice
            if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#FOUND_PROVIDERS[@]}" ]; then
                idx=$((choice - 1))
                SELECTED_ENV_VAR="${FOUND_ENV_VARS[$idx]}"
                SELECTED_PROVIDER_ID="${PROVIDER_IDS[$SELECTED_ENV_VAR]}"

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
    choice=$?

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
            echo -e "${YELLOW}Skipped.${NC} Add your API key later:"
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
if $PYTHON_CMD -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo -n "  ⬡ aden_tools... "
if $PYTHON_CMD -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo -n "  ⬡ litellm... "
if $PYTHON_CMD -c "import litellm" > /dev/null 2>&1; then
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
    SELECTED_MODEL="${DEFAULT_MODELS[$SELECTED_PROVIDER_ID]}"
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
