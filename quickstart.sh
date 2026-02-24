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
        read -r -p "Enter choice (1-${#options[@]}): " choice || true
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

# Install all workspace packages (core + tools) from workspace root
echo -n "  Installing workspace packages... "
cd "$SCRIPT_DIR"

if [ -f "pyproject.toml" ]; then
    if uv sync > /dev/null 2>&1; then
        echo -e "${GREEN}  ✓ workspace packages installed${NC}"
    else
        echo -e "${RED}  ✗ workspace installation failed${NC}"
        exit 1
    fi
else
    echo -e "${RED}failed (no root pyproject.toml)${NC}"
    exit 1
fi

# Install Playwright browser
echo -n "  Installing Playwright browser... "
if uv run python -c "import playwright" > /dev/null 2>&1; then
    if uv run python -m playwright install chromium > /dev/null 2>&1; then
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

# ============================================================
# Step 3: Verify Python Imports
# ============================================================

echo -e "${BLUE}Step 3: Verifying Python imports...${NC}"
echo ""

IMPORT_ERRORS=0

# Test imports using workspace venv via uv run
if uv run python -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ framework imports OK${NC}"
else
    echo -e "${RED}  ✗ framework import failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

if uv run python -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ aden_tools imports OK${NC}"
else
    echo -e "${RED}  ✗ aden_tools import failed${NC}"
    IMPORT_ERRORS=$((IMPORT_ERRORS + 1))
fi

if uv run python -c "import litellm" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ litellm imports OK${NC}"
else
    echo -e "${YELLOW}  ⚠ litellm import issues (may be OK)${NC}"
fi

if uv run python -c "from framework.mcp import agent_builder_server" > /dev/null 2>&1; then
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
        ["anthropic"]="claude-haiku-4-5"
        ["openai"]="gpt-5-mini"
        ["gemini"]="gemini-3-flash-preview"
        ["groq"]="moonshotai/kimi-k2-instruct-0905"
        ["cerebras"]="zai-glm-4.7"
        ["mistral"]="mistral-large-latest"
        ["together_ai"]="meta-llama/Llama-3.3-70B-Instruct-Turbo"
        ["deepseek"]="deepseek-chat"
    )

    # Model choices per provider: composite-key associative arrays
    # Keys: "provider:index" -> value
    declare -A MODEL_CHOICES_ID=(
        ["anthropic:0"]="claude-opus-4-6"
        ["anthropic:1"]="claude-sonnet-4-5-20250929"
        ["anthropic:2"]="claude-sonnet-4-20250514"
        ["anthropic:3"]="claude-haiku-4-5-20251001"
        ["openai:0"]="gpt-5.2"
        ["openai:1"]="gpt-5-mini"
        ["openai:2"]="gpt-5-nano"
        ["gemini:0"]="gemini-3-flash-preview"
        ["gemini:1"]="gemini-3-pro-preview"
        ["groq:0"]="moonshotai/kimi-k2-instruct-0905"
        ["groq:1"]="openai/gpt-oss-120b"
        ["cerebras:0"]="zai-glm-4.7"
        ["cerebras:1"]="qwen3-235b-a22b-instruct-2507"
    )

    declare -A MODEL_CHOICES_LABEL=(
        ["anthropic:0"]="Opus 4.6 - Most capable (recommended)"
        ["anthropic:1"]="Sonnet 4.5 - Best balance"
        ["anthropic:2"]="Sonnet 4 - Fast + capable"
        ["anthropic:3"]="Haiku 4.5 - Fast + cheap"
        ["openai:0"]="GPT-5.2 - Most capable (recommended)"
        ["openai:1"]="GPT-5 Mini - Fast + cheap"
        ["openai:2"]="GPT-5 Nano - Fastest"
        ["gemini:0"]="Gemini 3 Flash - Fast (recommended)"
        ["gemini:1"]="Gemini 3 Pro - Best quality"
        ["groq:0"]="Kimi K2 - Best quality (recommended)"
        ["groq:1"]="GPT-OSS 120B - Fast reasoning"
        ["cerebras:0"]="ZAI-GLM 4.7 - Best quality (recommended)"
        ["cerebras:1"]="Qwen3 235B - Frontier reasoning"
    )

    declare -A MODEL_CHOICES_MAXTOKENS=(
        ["anthropic:0"]=32768
        ["anthropic:1"]=16384
        ["anthropic:2"]=8192
        ["anthropic:3"]=8192
        ["openai:0"]=16384
        ["openai:1"]=16384
        ["openai:2"]=16384
        ["gemini:0"]=8192
        ["gemini:1"]=8192
        ["groq:0"]=8192
        ["groq:1"]=8192
        ["cerebras:0"]=8192
        ["cerebras:1"]=8192
    )

    declare -A MODEL_CHOICES_COUNT=(
        ["anthropic"]=4
        ["openai"]=3
        ["gemini"]=2
        ["groq"]=2
        ["cerebras"]=2
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

    get_model_choice_count() {
        echo "${MODEL_CHOICES_COUNT[$1]:-0}"
    }

    get_model_choice_id() {
        echo "${MODEL_CHOICES_ID[$1:$2]}"
    }

    get_model_choice_label() {
        echo "${MODEL_CHOICES_LABEL[$1:$2]}"
    }

    get_model_choice_maxtokens() {
        echo "${MODEL_CHOICES_MAXTOKENS[$1:$2]}"
    }
else
    # Bash 3.2 - use parallel indexed arrays
    PROVIDER_ENV_VARS=(ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY GROQ_API_KEY CEREBRAS_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY DEEPSEEK_API_KEY)
    PROVIDER_DISPLAY_NAMES=("Anthropic (Claude)" "OpenAI (GPT)" "Google Gemini" "Google AI" "Groq" "Cerebras" "Mistral" "Together AI" "DeepSeek")
    PROVIDER_ID_LIST=(anthropic openai gemini google groq cerebras mistral together deepseek)

    # Default models by provider id (parallel arrays)
    MODEL_PROVIDER_IDS=(anthropic openai gemini groq cerebras mistral together_ai deepseek)
    MODEL_DEFAULTS=("claude-opus-4-6" "gpt-5.2" "gemini-3-flash-preview" "moonshotai/kimi-k2-instruct-0905" "zai-glm-4.7" "mistral-large-latest" "meta-llama/Llama-3.3-70B-Instruct-Turbo" "deepseek-chat")

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

    # Model choices per provider - flat parallel arrays with provider offsets
    # Provider order: anthropic(4), openai(3), gemini(2), groq(2), cerebras(2)
    MC_PROVIDERS=(anthropic anthropic anthropic anthropic openai openai openai gemini gemini groq groq cerebras cerebras)
    MC_IDS=("claude-opus-4-6" "claude-sonnet-4-5-20250929" "claude-sonnet-4-20250514" "claude-haiku-4-5-20251001" "gpt-5.2" "gpt-5-mini" "gpt-5-nano" "gemini-3-flash-preview" "gemini-3-pro-preview" "moonshotai/kimi-k2-instruct-0905" "openai/gpt-oss-120b" "zai-glm-4.7" "qwen3-235b-a22b-instruct-2507")
    MC_LABELS=("Opus 4.6 - Most capable (recommended)" "Sonnet 4.5 - Best balance" "Sonnet 4 - Fast + capable" "Haiku 4.5 - Fast + cheap" "GPT-5.2 - Most capable (recommended)" "GPT-5 Mini - Fast + cheap" "GPT-5 Nano - Fastest" "Gemini 3 Flash - Fast (recommended)" "Gemini 3 Pro - Best quality" "Kimi K2 - Best quality (recommended)" "GPT-OSS 120B - Fast reasoning" "ZAI-GLM 4.7 - Best quality (recommended)" "Qwen3 235B - Frontier reasoning")
    MC_MAXTOKENS=(32768 16384 8192 8192 16384 16384 16384 8192 8192 8192 8192 8192 8192)

    # Helper: get number of model choices for a provider
    get_model_choice_count() {
        local provider_id="$1"
        local count=0
        local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$provider_id" ]; then
                count=$((count + 1))
            fi
            i=$((i + 1))
        done
        echo "$count"
    }

    # Helper: get model choice id by provider and index (0-based within provider)
    get_model_choice_id() {
        local provider_id="$1"
        local idx="$2"
        local count=0
        local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$provider_id" ]; then
                if [ $count -eq "$idx" ]; then
                    echo "${MC_IDS[$i]}"
                    return
                fi
                count=$((count + 1))
            fi
            i=$((i + 1))
        done
    }

    # Helper: get model choice label by provider and index
    get_model_choice_label() {
        local provider_id="$1"
        local idx="$2"
        local count=0
        local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$provider_id" ]; then
                if [ $count -eq "$idx" ]; then
                    echo "${MC_LABELS[$i]}"
                    return
                fi
                count=$((count + 1))
            fi
            i=$((i + 1))
        done
    }

    # Helper: get model choice max_tokens by provider and index
    get_model_choice_maxtokens() {
        local provider_id="$1"
        local idx="$2"
        local count=0
        local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$provider_id" ]; then
                if [ $count -eq "$idx" ]; then
                    echo "${MC_MAXTOKENS[$i]}"
                    return
                fi
                count=$((count + 1))
            fi
            i=$((i + 1))
        done
    }
fi

# Configuration directory
HIVE_CONFIG_DIR="$HOME/.hive"
HIVE_CONFIG_FILE="$HIVE_CONFIG_DIR/configuration.json"

# Detect user's shell rc file
detect_shell_rc() {
    local shell_name
    shell_name=$(basename "$SHELL")

    case "$shell_name" in
        zsh)
            if [ -f "$HOME/.zshrc" ]; then
                echo "$HOME/.zshrc"
            else
                echo "$HOME/.zshenv"
            fi
            ;;
        bash)
            if [ -f "$HOME/.bashrc" ]; then
                echo "$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then
                echo "$HOME/.bash_profile"
            else
                echo "$HOME/.profile"
            fi
            ;;
        *)
            # Fallback to .profile for other shells
            echo "$HOME/.profile"
            ;;
    esac
}

SHELL_RC_FILE=$(detect_shell_rc)
SHELL_NAME=$(basename "$SHELL")

# Prompt the user to choose a model for their selected provider.
# Sets SELECTED_MODEL and SELECTED_MAX_TOKENS.
prompt_model_selection() {
    local provider_id="$1"
    local count
    count="$(get_model_choice_count "$provider_id")"

    if [ "$count" -eq 0 ]; then
        # No curated choices for this provider (e.g. Mistral, DeepSeek)
        SELECTED_MODEL="$(get_default_model "$provider_id")"
        SELECTED_MAX_TOKENS=8192
        return
    fi

    if [ "$count" -eq 1 ]; then
        # Only one choice — auto-select
        SELECTED_MODEL="$(get_model_choice_id "$provider_id" 0)"
        SELECTED_MAX_TOKENS="$(get_model_choice_maxtokens "$provider_id" 0)"
        return
    fi

    # Multiple choices — show menu
    echo ""
    echo -e "${BOLD}Select a model:${NC}"
    echo ""

    local i=0
    while [ $i -lt "$count" ]; do
        local label
        label="$(get_model_choice_label "$provider_id" "$i")"
        local mid
        mid="$(get_model_choice_id "$provider_id" "$i")"
        local num=$((i + 1))
        echo -e "  ${CYAN}$num)${NC} $label  ${DIM}($mid)${NC}"
        i=$((i + 1))
    done
    echo ""

    local choice
    while true; do
        read -r -p "Enter choice (1-$count): " choice || true
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$count" ]; then
            local idx=$((choice - 1))
            SELECTED_MODEL="$(get_model_choice_id "$provider_id" "$idx")"
            SELECTED_MAX_TOKENS="$(get_model_choice_maxtokens "$provider_id" "$idx")"
            echo ""
            echo -e "${GREEN}⬢${NC} Model: ${DIM}$SELECTED_MODEL${NC}"
            return
        fi
        echo -e "${RED}Invalid choice. Please enter 1-$count${NC}"
    done
}

# Function to save configuration
# Args: provider_id env_var model max_tokens [use_claude_code_sub] [api_base]
save_configuration() {
    local provider_id="$1"
    local env_var="$2"
    local model="$3"
    local max_tokens="$4"
    local use_claude_code_sub="${5:-}"
    local api_base="${6:-}"

    # Fallbacks if not provided
    if [ -z "$model" ]; then
        model="$(get_default_model "$provider_id")"
    fi
    if [ -z "$max_tokens" ]; then
        max_tokens=8192
    fi

    mkdir -p "$HIVE_CONFIG_DIR"

    $PYTHON_CMD -c "
import json
config = {
    'llm': {
        'provider': '$provider_id',
        'model': '$model',
        'max_tokens': $max_tokens,
        'api_key_env_var': '$env_var'
    },
    'created_at': '$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")'
}
if '$use_claude_code_sub' == 'true':
    config['llm']['use_claude_code_subscription'] = True
    # No api_key_env_var needed for Claude Code subscription
    config['llm'].pop('api_key_env_var', None)
if '$api_base':
    config['llm']['api_base'] = '$api_base'
with open('$HIVE_CONFIG_FILE', 'w') as f:
    json.dump(config, f, indent=2)
print(json.dumps(config, indent=2))
" 2>/dev/null
}

# Source shell rc file to pick up existing env vars (temporarily disable set -e)
set +e
if [ -f "$SHELL_RC_FILE" ]; then
    # Extract only export statements to avoid running shell config commands
    eval "$(grep -E '^export [A-Z_]+=' "$SHELL_RC_FILE" 2>/dev/null)"
fi
set -e

# Find all available API keys
FOUND_PROVIDERS=()      # Display names for UI
FOUND_ENV_VARS=()       # Corresponding env var names
SELECTED_PROVIDER_ID="" # Will hold the chosen provider ID
SELECTED_ENV_VAR=""     # Will hold the chosen env var
SELECTED_MODEL=""       # Will hold the chosen model ID
SELECTED_MAX_TOKENS=8192 # Will hold the chosen max_tokens
SUBSCRIPTION_MODE=""    # "claude_code" | "zai_code" | ""

# ── Subscription mode detection ──────────────────────────────
# Claude Code subscription: default when ~/.claude/.credentials.json exists
CLAUDE_CRED_FILE="$HOME/.claude/.credentials.json"
if [ -f "$CLAUDE_CRED_FILE" ]; then
    echo -e "  ${GREEN}⬢${NC} Claude Code subscription detected"
    echo -e "    ${DIM}~/.claude/.credentials.json${NC}"
    echo -e "    ${DIM}Default: claude-opus-4-6 | max_tokens: 32768${NC}"
    echo ""
    if prompt_yes_no "Use Claude Code subscription? (no API key needed)"; then
        SUBSCRIPTION_MODE="claude_code"
        SELECTED_PROVIDER_ID="anthropic"
        SELECTED_MODEL="claude-opus-4-6"
        SELECTED_MAX_TOKENS=32768
        echo ""
        echo -e "${GREEN}⬢${NC} Using Claude Code subscription"
    fi
fi

# ZAI Code subscription: check for ZAI_API_KEY
if [ -z "$SUBSCRIPTION_MODE" ] && [ -n "${ZAI_API_KEY:-}" ]; then
    echo -e "  ${GREEN}⬢${NC} Found ZAI Code API key"
    echo ""
    if prompt_yes_no "Use your ZAI Code subscription?"; then
        SUBSCRIPTION_MODE="zai_code"
        SELECTED_PROVIDER_ID="openai"
        SELECTED_ENV_VAR="ZAI_API_KEY"
        SELECTED_MODEL="glm-5"
        SELECTED_MAX_TOKENS=32768
        echo ""
        echo -e "${GREEN}⬢${NC} Using ZAI Code subscription"
        echo -e "  ${DIM}Model: glm-5 | API: api.z.ai${NC}"
    fi
fi

# Skip normal provider detection if a subscription mode was selected
if [ -n "$SUBSCRIPTION_MODE" ]; then
    # Jump ahead — SELECTED_PROVIDER_ID is already set
    :
elif [ "$USE_ASSOC_ARRAYS" = true ]; then
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

    # Show all found providers + ZAI subscription + Other
    echo -e "${BOLD}Select your default LLM provider:${NC}"
    echo ""

    i=1
    for provider in "${FOUND_PROVIDERS[@]}"; do
        echo -e "  ${CYAN}$i)${NC} $provider"
        i=$((i + 1))
    done
    # Only show ZAI Code Subscription if the API key already exists
    if [ -n "${ZAI_API_KEY:-}" ]; then
        ZAI_CHOICE=$i
        echo -e "  ${CYAN}$i)${NC} ZAI Code Subscription  ${DIM}(use your ZAI Code plan)${NC}"
        i=$((i + 1))
    else
        ZAI_CHOICE=-1  # invalid choice, won't match
    fi
    echo -e "  ${CYAN}$i)${NC} Other"
    max_choice=$i
    echo ""

    while true; do
        read -r -p "Enter choice (1-$max_choice): " choice || true
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$max_choice" ]; then
            if [ "$choice" -eq "$max_choice" ]; then
                # Fall through to the manual provider selection below
                break
            elif [ "$choice" -eq "$ZAI_CHOICE" ]; then
                # ZAI Code Subscription
                SUBSCRIPTION_MODE="zai_code"
                SELECTED_PROVIDER_ID="openai"
                SELECTED_ENV_VAR="ZAI_API_KEY"
                SELECTED_MODEL="glm-5"
                SELECTED_MAX_TOKENS=32768
                echo ""
                echo -e "${GREEN}⬢${NC} Using ZAI Code subscription"
                echo -e "  ${DIM}Model: glm-5 | API: api.z.ai${NC}"
                break
            fi
            idx=$((choice - 1))
            SELECTED_ENV_VAR="${FOUND_ENV_VARS[$idx]}"
            SELECTED_PROVIDER_ID="$(get_provider_id "$SELECTED_ENV_VAR")"

            echo ""
            echo -e "${GREEN}⬢${NC} Selected: ${FOUND_PROVIDERS[$idx]}"

            prompt_model_selection "$SELECTED_PROVIDER_ID"
            break
        fi
        echo -e "${RED}Invalid choice. Please enter 1-$max_choice${NC}"
    done
fi

if [ -z "$SELECTED_PROVIDER_ID" ]; then
    echo ""
    echo -e "${BOLD}Select your LLM provider:${NC}"
    echo ""
    echo -e "  ${CYAN}${BOLD}Subscription modes (no API key purchase needed):${NC}"
    echo -e "  ${CYAN}1)${NC} Claude Code Subscription  ${DIM}(use your Claude Max/Pro plan)${NC}"
    echo -e "  ${CYAN}2)${NC} ZAI Code Subscription     ${DIM}(use your ZAI Code plan)${NC}"
    echo ""
    echo -e "  ${CYAN}${BOLD}API key providers:${NC}"
    echo -e "  ${CYAN}3)${NC} Anthropic (Claude) - Recommended"
    echo -e "  ${CYAN}4)${NC} OpenAI (GPT)"
    echo -e "  ${CYAN}5)${NC} Google Gemini - Free tier available"
    echo -e "  ${CYAN}6)${NC} Groq - Fast, free tier"
    echo -e "  ${CYAN}7)${NC} Cerebras - Fast, free tier"
    echo -e "  ${CYAN}8)${NC} Skip for now"
    echo ""

    while true; do
        read -r -p "Enter choice (1-8): " choice || true
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le 8 ]; then
            break
        fi
        echo -e "${RED}Invalid choice. Please enter 1-8${NC}"
    done

    case $choice in
        1)
            # Claude Code Subscription
            CLAUDE_CRED_FILE="$HOME/.claude/.credentials.json"
            if [ ! -f "$CLAUDE_CRED_FILE" ]; then
                echo ""
                echo -e "${YELLOW}  ~/.claude/.credentials.json not found.${NC}"
                echo -e "  Run ${CYAN}claude${NC} first to authenticate with your Claude subscription,"
                echo -e "  then run this quickstart again."
                echo ""
                SELECTED_PROVIDER_ID=""
            else
                SUBSCRIPTION_MODE="claude_code"
                SELECTED_PROVIDER_ID="anthropic"
                echo ""
                echo -e "${GREEN}⬢${NC} Using Claude Code subscription"
            fi
            ;;
        2)
            # ZAI Code Subscription
            SUBSCRIPTION_MODE="zai_code"
            SELECTED_PROVIDER_ID="openai"
            SELECTED_ENV_VAR="ZAI_API_KEY"
            SELECTED_MODEL="glm-5"
            SELECTED_MAX_TOKENS=32768
            PROVIDER_NAME="ZAI"
            echo ""
            echo -e "${GREEN}⬢${NC} Using ZAI Code subscription"
            echo -e "  ${DIM}Model: glm-5 | API: api.z.ai${NC}"
            ;;
        3)
            SELECTED_ENV_VAR="ANTHROPIC_API_KEY"
            SELECTED_PROVIDER_ID="anthropic"
            PROVIDER_NAME="Anthropic"
            SIGNUP_URL="https://console.anthropic.com/settings/keys"
            ;;
        4)
            SELECTED_ENV_VAR="OPENAI_API_KEY"
            SELECTED_PROVIDER_ID="openai"
            PROVIDER_NAME="OpenAI"
            SIGNUP_URL="https://platform.openai.com/api-keys"
            ;;
        5)
            SELECTED_ENV_VAR="GEMINI_API_KEY"
            SELECTED_PROVIDER_ID="gemini"
            PROVIDER_NAME="Google Gemini"
            SIGNUP_URL="https://aistudio.google.com/apikey"
            ;;
        6)
            SELECTED_ENV_VAR="GROQ_API_KEY"
            SELECTED_PROVIDER_ID="groq"
            PROVIDER_NAME="Groq"
            SIGNUP_URL="https://console.groq.com/keys"
            ;;
        7)
            SELECTED_ENV_VAR="CEREBRAS_API_KEY"
            SELECTED_PROVIDER_ID="cerebras"
            PROVIDER_NAME="Cerebras"
            SIGNUP_URL="https://cloud.cerebras.ai/"
            ;;
        8)
            echo ""
            echo -e "${YELLOW}Skipped.${NC} An LLM API key is required to test and use worker agents."
            echo -e "Add your API key later by running:"
            echo ""
            echo -e "  ${CYAN}echo 'export ANTHROPIC_API_KEY=\"your-key\"' >> $SHELL_RC_FILE${NC}"
            echo ""
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
            ;;
    esac

    # For API-key providers: prompt for key if not already set
    if [ -z "$SUBSCRIPTION_MODE" ] && [ -n "$SELECTED_ENV_VAR" ] && [ -z "${!SELECTED_ENV_VAR}" ]; then
        echo ""
        echo -e "Get your API key from: ${CYAN}$SIGNUP_URL${NC}"
        echo ""
        read -r -p "Paste your $PROVIDER_NAME API key (or press Enter to skip): " API_KEY

        if [ -n "$API_KEY" ]; then
            # Save to shell rc file
            echo "" >> "$SHELL_RC_FILE"
            echo "# Hive Agent Framework - $PROVIDER_NAME API key" >> "$SHELL_RC_FILE"
            echo "export $SELECTED_ENV_VAR=\"$API_KEY\"" >> "$SHELL_RC_FILE"
            export "$SELECTED_ENV_VAR=$API_KEY"
            echo ""
            echo -e "${GREEN}⬢${NC} API key saved to $SHELL_RC_FILE"
        else
            echo ""
            echo -e "${YELLOW}Skipped.${NC} Add your API key to $SHELL_RC_FILE when ready."
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
        fi
    fi

fi

# For ZAI subscription: always prompt for API key
if [ "$SUBSCRIPTION_MODE" = "zai_code" ]; then
    echo ""
    read -r -p "Paste your ZAI API key (or press Enter to skip): " API_KEY

    if [ -n "$API_KEY" ]; then
        echo "" >> "$SHELL_RC_FILE"
        echo "# Hive Agent Framework - ZAI Code subscription API key" >> "$SHELL_RC_FILE"
        echo "export ZAI_API_KEY=\"$API_KEY\"" >> "$SHELL_RC_FILE"
        export ZAI_API_KEY="$API_KEY"
        echo ""
        echo -e "${GREEN}⬢${NC} ZAI API key saved to $SHELL_RC_FILE"
    else
        echo ""
        echo -e "${YELLOW}Skipped.${NC} Add your ZAI API key to $SHELL_RC_FILE when ready:"
        echo -e "  ${CYAN}echo 'export ZAI_API_KEY=\"your-key\"' >> $SHELL_RC_FILE${NC}"
        SELECTED_ENV_VAR=""
        SELECTED_PROVIDER_ID=""
        SUBSCRIPTION_MODE=""
    fi
fi

# Prompt for model if not already selected (manual provider path)
if [ -n "$SELECTED_PROVIDER_ID" ] && [ -z "$SELECTED_MODEL" ]; then
    prompt_model_selection "$SELECTED_PROVIDER_ID"
fi

# Save configuration if a provider was selected
if [ -n "$SELECTED_PROVIDER_ID" ]; then
    echo ""
    echo -n "  Saving configuration... "
    if [ "$SUBSCRIPTION_MODE" = "claude_code" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "true" "" > /dev/null
    elif [ "$SUBSCRIPTION_MODE" = "zai_code" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "" "https://api.z.ai/api/coding/paas/v4" > /dev/null
    else
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" > /dev/null
    fi
    echo -e "${GREEN}⬢${NC}"
    echo -e "  ${DIM}~/.hive/configuration.json${NC}"
fi

echo ""

# ============================================================
# Step 5: Initialize Credential Store
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 5: Initializing credential store...${NC}"
echo ""
echo -e "${DIM}The credential store encrypts API keys and secrets for your agents.${NC}"
echo ""

HIVE_CRED_DIR="$HOME/.hive/credentials"

# Check if HIVE_CREDENTIAL_KEY already exists (from env or shell rc)
if [ -n "$HIVE_CREDENTIAL_KEY" ]; then
    echo -e "${GREEN}  ✓ HIVE_CREDENTIAL_KEY already set${NC}"
else
    # Generate a new Fernet encryption key
    echo -n "  Generating encryption key... "
    GENERATED_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" 2>/dev/null)

    if [ -z "$GENERATED_KEY" ]; then
        echo -e "${RED}failed${NC}"
        echo -e "${YELLOW}  ⚠ Credential store will not be available.${NC}"
        echo -e "${YELLOW}    You can set HIVE_CREDENTIAL_KEY manually later.${NC}"
    else
        echo -e "${GREEN}ok${NC}"

        # Save to shell rc file
        echo "" >> "$SHELL_RC_FILE"
        echo "# Encryption key for Hive credential store (~/.hive/credentials)" >> "$SHELL_RC_FILE"
        echo "export HIVE_CREDENTIAL_KEY=\"$GENERATED_KEY\"" >> "$SHELL_RC_FILE"
        export HIVE_CREDENTIAL_KEY="$GENERATED_KEY"

        echo -e "${GREEN}  ✓ Encryption key saved to $SHELL_RC_FILE${NC}"
    fi
fi

# Create credential store directories
if [ -n "$HIVE_CREDENTIAL_KEY" ]; then
    mkdir -p "$HIVE_CRED_DIR/credentials"
    mkdir -p "$HIVE_CRED_DIR/metadata"

    # Initialize the metadata index
    if [ ! -f "$HIVE_CRED_DIR/metadata/index.json" ]; then
        echo '{"credentials": {}, "version": "1.0"}' > "$HIVE_CRED_DIR/metadata/index.json"
    fi

    echo -e "${GREEN}  ✓ Credential store initialized at ~/.hive/credentials/${NC}"

    # Verify the store works
    echo -n "  Verifying credential store... "
    if uv run python -c "
from framework.credentials.storage import EncryptedFileStorage
storage = EncryptedFileStorage()
print('ok')
" 2>/dev/null | grep -q "ok"; then
        echo -e "${GREEN}ok${NC}"
    else
        echo -e "${YELLOW}--${NC}"
    fi
fi

echo ""

# ============================================================
# Step 6: Verify Setup
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 6: Verifying installation...${NC}"
echo ""

ERRORS=0

# Test imports
echo -n "  ⬡ framework... "
if uv run python -c "import framework" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo -n "  ⬡ aden_tools... "
if uv run python -c "import aden_tools" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${RED}failed${NC}"
    ERRORS=$((ERRORS + 1))
fi

echo -n "  ⬡ litellm... "
if uv run python -c "import litellm" > /dev/null 2>&1; then
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

echo -n "  ⬡ codex CLI... "
if command -v codex > /dev/null 2>&1; then
    CODEX_VERSION=$(codex --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0.0.0")
    # Compare version >= 0.101.0
    CODEX_MAJOR=$(echo "$CODEX_VERSION" | cut -d. -f1)
    CODEX_MINOR=$(echo "$CODEX_VERSION" | cut -d. -f2)
    if [ "$CODEX_MAJOR" -gt 0 ] 2>/dev/null || { [ "$CODEX_MAJOR" -eq 0 ] && [ "$CODEX_MINOR" -ge 101 ]; } 2>/dev/null; then
        echo -e "${GREEN}${CODEX_VERSION}${NC}"
        CODEX_AVAILABLE=true
    else
        echo -e "${YELLOW}${CODEX_VERSION} (upgrade to 0.101.0+)${NC}"
        CODEX_AVAILABLE=false
    fi
else
    echo -e "${YELLOW}--${NC}"
    CODEX_AVAILABLE=false
fi

echo -n "  ⬡ local settings... "
if [ -f "$SCRIPT_DIR/.claude/settings.local.json" ]; then
    echo -e "${GREEN}ok${NC}"
elif [ -f "$SCRIPT_DIR/.claude/settings.local.json.example" ]; then
    cp "$SCRIPT_DIR/.claude/settings.local.json.example" "$SCRIPT_DIR/.claude/settings.local.json"
    echo -e "${GREEN}copied from example${NC}"
else
    echo -e "${YELLOW}--${NC}"
fi

echo -n "  ⬡ credential store... "
if [ -n "$HIVE_CREDENTIAL_KEY" ] && [ -d "$HOME/.hive/credentials/credentials" ]; then
    echo -e "${GREEN}ok${NC}"
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
# Step 7: Install hive CLI globally
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 7: Installing hive CLI...${NC}"
echo ""

# Ensure ~/.local/bin exists and is in PATH
mkdir -p "$HOME/.local/bin"

# Create/update symlink
HIVE_SCRIPT="$SCRIPT_DIR/hive"
HIVE_LINK="$HOME/.local/bin/hive"

if [ -L "$HIVE_LINK" ] || [ -e "$HIVE_LINK" ]; then
    rm -f "$HIVE_LINK"
fi

ln -s "$HIVE_SCRIPT" "$HIVE_LINK"
echo -e "${GREEN}  ✓ hive CLI installed to ~/.local/bin/hive${NC}"

# Check if ~/.local/bin is in PATH
if echo "$PATH" | grep -q "$HOME/.local/bin"; then
    echo -e "${GREEN}  ✓ ~/.local/bin is in PATH${NC}"
else
    echo -e "${YELLOW}  ⚠ Add ~/.local/bin to your PATH:${NC}"
    echo -e "     ${DIM}echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.bashrc${NC}"
    echo -e "     ${DIM}source ~/.bashrc${NC}"
fi

echo ""

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
    if [ -z "$SELECTED_MODEL" ]; then
        SELECTED_MODEL="$(get_default_model "$SELECTED_PROVIDER_ID")"
    fi
    echo -e "${BOLD}Default LLM:${NC}"
    if [ "$SUBSCRIPTION_MODE" = "claude_code" ]; then
        echo -e "  ${GREEN}⬢${NC} Claude Code Subscription → ${DIM}$SELECTED_MODEL${NC}"
        echo -e "  ${DIM}Token auto-refresh from ~/.claude/.credentials.json${NC}"
    elif [ "$SUBSCRIPTION_MODE" = "zai_code" ]; then
        echo -e "  ${GREEN}⬢${NC} ZAI Code Subscription → ${DIM}$SELECTED_MODEL${NC}"
        echo -e "  ${DIM}API: api.z.ai (OpenAI-compatible)${NC}"
    else
        echo -e "  ${CYAN}$SELECTED_PROVIDER_ID${NC} → ${DIM}$SELECTED_MODEL${NC}"
    fi
    echo ""
fi

# Show credential store status
if [ -n "$HIVE_CREDENTIAL_KEY" ]; then
    echo -e "${BOLD}Credential Store:${NC}"
    echo -e "  ${GREEN}⬢${NC} ${DIM}~/.hive/credentials/${NC}  (encrypted)"
    echo -e "  ${DIM}Set up agent credentials with:${NC} ${CYAN}/setup-credentials${NC}"
    echo ""
fi

echo -e "${BOLD}Build a New Agent (Claude):${NC}"
echo ""
echo -e "  1. Open Claude Code in this directory:"
echo -e "     ${CYAN}claude${NC}"
echo ""
echo -e "  2. Build a new agent:"
echo -e "     ${CYAN}/hive${NC}"
echo ""
echo -e "  3. Test an existing agent:"
echo -e "     ${CYAN}/hive-test${NC}"
echo ""

# Show Codex instructions if available
if [ "$CODEX_AVAILABLE" = true ]; then
    echo -e "${BOLD}Build a New Agent (Codex):${NC}"
    echo ""
    echo -e "  Codex ${GREEN}${CODEX_VERSION}${NC} is available. To use it with Hive:"
    echo -e "  1. Restart your terminal (or open a new one)"
    echo -e "  2. Run: ${CYAN}codex${NC}"
    echo -e "  3. Type: ${CYAN}use hive${NC}"
    echo ""
fi

# Prompt user to source shell config or start new terminal
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}⚠️  IMPORTANT: Load your new configuration${NC}"
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  Your API keys have been saved to ${CYAN}$SHELL_RC_FILE${NC}"
echo -e "  To use them, either:"
echo ""
echo -e "  ${GREEN}Option 1:${NC} Source your shell config now:"
echo -e "     ${CYAN}source $SHELL_RC_FILE${NC}"
echo ""
echo -e "  ${GREEN}Option 2:${NC} Open a new terminal window"
echo ""
echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${BOLD}Run an Agent:${NC}"
echo ""
echo -e "  Launch the interactive dashboard to browse and run agents:"
echo -e "  You can start an example agent or an agent built by yourself:"
echo -e "     ${CYAN}hive tui${NC}"
echo ""
echo -e "${DIM}Run ./quickstart.sh again to reconfigure.${NC}"
echo ""
