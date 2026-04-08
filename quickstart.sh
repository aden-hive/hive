#!/bin/bash
#
# quickstart.sh - Interactive onboarding for Aden Agent Framework
#
# An interactive setup wizard that:
# 1. Installs Python dependencies
# 2. Checks for Chrome/Edge browser for web automation
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

# Hive LLM router endpoint
HIVE_LLM_ENDPOINT="https://api.adenhq.com"
HIVE_LLM_AVAILABILITY_ENDPOINT="$HIVE_LLM_ENDPOINT/v1/gateway/availability"

check_hive_llm_availability() {
    local from_source="$1"

    if ! command -v curl >/dev/null 2>&1; then
        return 2
    fi

    local response
    response="$(curl -fsSL --max-time 5 "${HIVE_LLM_AVAILABILITY_ENDPOINT}?from=${from_source}" 2>/dev/null)" || return 2
    if [ "$response" = "true" ]; then
        return 0
    fi
    return 1
}

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

# Check for Node.js (needed for frontend dashboard)
NODE_AVAILABLE=false
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    NODE_MAJOR=$(echo "$NODE_VERSION" | sed 's/v//' | cut -d. -f1)
    if [ "$NODE_MAJOR" -ge 20 ]; then
        echo -e "${GREEN}  ✓ Node.js $NODE_VERSION${NC}"
        NODE_AVAILABLE=true
    else
        echo -e "${YELLOW}  ⚠ Node.js $NODE_VERSION found (20+ required for frontend)${NC}"
        echo -e "${YELLOW}  Installing Node.js 20 via nvm...${NC}"
        # Install nvm if not present
        if [ -z "${NVM_DIR:-}" ] || [ ! -s "$NVM_DIR/nvm.sh" ]; then
            export NVM_DIR="$HOME/.nvm"
            curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash 2>/dev/null
        fi
        # Source nvm and install Node 20
        [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
        if nvm install 20 > /dev/null 2>&1 && nvm use 20 > /dev/null 2>&1; then
            NODE_VERSION=$(node --version)
            echo -e "${GREEN}  ✓ Node.js $NODE_VERSION installed via nvm${NC}"
            NODE_AVAILABLE=true
        else
            echo -e "${RED}  ✗ Node.js installation failed${NC}"
            echo -e "${DIM}    Install manually from https://nodejs.org${NC}"
        fi
    fi
else
    echo -e "${YELLOW}  Node.js not found. Installing via nvm...${NC}"
    # Install nvm if not present
    if [ -z "${NVM_DIR:-}" ] || [ ! -s "$NVM_DIR/nvm.sh" ]; then
        export NVM_DIR="$HOME/.nvm"
        if ! curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh 2>/dev/null | bash 2>/dev/null; then
            echo -e "${RED}  ✗ nvm installation failed${NC}"
            echo -e "${DIM}    Install Node.js 20+ manually from https://nodejs.org${NC}"
        fi
    fi
    # Source nvm and install Node 20
    if [ -s "${NVM_DIR:-$HOME/.nvm}/nvm.sh" ]; then
        export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
        . "$NVM_DIR/nvm.sh"
        if nvm install 20 > /dev/null 2>&1 && nvm use 20 > /dev/null 2>&1; then
            NODE_VERSION=$(node --version)
            echo -e "${GREEN}  ✓ Node.js $NODE_VERSION installed via nvm${NC}"
            NODE_AVAILABLE=true
        else
            echo -e "${RED}  ✗ Node.js installation failed${NC}"
            echo -e "${DIM}    Install manually from https://nodejs.org${NC}"
        fi
    fi
fi

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

# Check for Chrome/Edge (required for GCU browser tools)
echo -n "  Checking for Chrome/Edge browser... "
# Check common browser locations
CHROME_FOUND=false
for browser in "google-chrome" "google-chrome-stable" "chromium" "chromium-browser" "microsoft-edge"; do
    if command -v "$browser" &> /dev/null; then
        CHROME_FOUND=true
        break
    fi
done
# Also check common desktop locations (for macOS/Windows)
if [ "$CHROME_FOUND" = false ]; then
    for path in "/Applications/Google Chrome.app" "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" "$HOME/Applications/Google Chrome.app" "$HOME/.local/share/applications/google-chrome.desktop"; do
        if [ -e "$path" ]; then
            CHROME_FOUND=true
            break
        fi
    done
fi
if [ "$CHROME_FOUND" = true ]; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${YELLOW}not found — install Chrome or Edge for browser tools${NC}"
fi

# Ensure playwright is installed for web scraping tools
echo -n "  Checking playwright installation... "
if uv run python -c "import playwright" > /dev/null 2>&1; then
    # Check if browser binaries are installed
    if uv run playwright install --dry-run chromium > /dev/null 2>&1; then
        echo -e "${GREEN}ok${NC}"
    else
        echo -e "${YELLOW}installing browser...${NC}"
        uv run playwright install chromium > /dev/null 2>&1
        if [ $? -eq 0 ]; then
            echo -e "  ${GREEN}✓ playwright chromium installed${NC}"
        else
            echo -e "  ${YELLOW}⚠ playwright browser installation failed (web scraping may not work)${NC}"
        fi
    fi
else
    echo -e "${YELLOW}not found — installing...${NC}"
    uv pip install playwright playwright-stealth > /dev/null 2>&1
    uv run playwright install chromium > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✓ playwright installed${NC}"
    else
        echo -e "  ${YELLOW}⚠ playwright installation failed (web scraping may not work)${NC}"
    fi
fi

cd "$SCRIPT_DIR"
echo ""
echo -e "${GREEN}⬢${NC} All packages installed"
echo ""

# Build frontend (if Node.js is available)
FRONTEND_BUILT=false
if [ "$NODE_AVAILABLE" = true ]; then
    echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Building frontend dashboard...${NC}"
    echo ""
    FRONTEND_DIR="$SCRIPT_DIR/core/frontend"
    if [ -f "$FRONTEND_DIR/package.json" ]; then
        echo -n "  Installing npm packages... "
        if (cd "$FRONTEND_DIR" && npm install --no-fund --no-audit) > /dev/null 2>&1; then
            echo -e "${GREEN}ok${NC}"
        else
            echo -e "${RED}failed${NC}"
            NODE_AVAILABLE=false
        fi

        if [ "$NODE_AVAILABLE" = true ]; then
            # Clean stale tsbuildinfo cache — tsc -b incremental builds fail
            # silently when these are out of sync with source files
            rm -f "$FRONTEND_DIR"/tsconfig*.tsbuildinfo
            echo -n "  Building frontend... "
            if (cd "$FRONTEND_DIR" && npm run build) > /dev/null 2>&1; then
                echo -e "${GREEN}ok${NC}"
                echo -e "${GREEN}  ✓ Frontend built → core/frontend/dist/${NC}"
                FRONTEND_BUILT=true
            else
                echo -e "${RED}failed${NC}"
                echo -e "${YELLOW}  ⚠ Frontend build failed. The web dashboard won't be available.${NC}"
                echo -e "${DIM}    Run 'cd core/frontend && npm run build' manually to debug.${NC}"
            fi
        fi
    fi
    echo ""
fi

# ============================================================
# Step 3: Verify Python Imports
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 3: Verifying Python imports...${NC}"
echo ""

IMPORT_ERRORS=0

# Batch check all imports in single process (reduces subprocess spawning overhead)
CHECK_RESULT=$(uv run python scripts/check_requirements.py framework aden_tools litellm 2>/dev/null)
CHECK_EXIT=$?

# Parse and display results
if [ $CHECK_EXIT -eq 0 ] || echo "$CHECK_RESULT" | grep -q "^{"; then
    # Try to parse JSON and display formatted results
    echo "$CHECK_RESULT" | uv run python -c "
import json, sys

GREEN, RED, YELLOW, NC = '\033[0;32m', '\033[0;31m', '\033[1;33m', '\033[0m'

try:
    data = json.loads(sys.stdin.read())
    modules = [
        ('framework', 'framework imports OK', True),
        ('aden_tools', 'aden_tools imports OK', True),
        ('litellm', 'litellm imports OK', False)
    ]
    import_errors = 0
    for mod, label, required in modules:
        status = data.get(mod, 'error: not checked')
        if status == 'ok':
            print(f'{GREEN}  ✓ {label}{NC}')
        elif required:
            print(f'{RED}  ✗ {label} failed{NC}')
            if status != 'error: not checked':
                print(f'    {status}')
            import_errors += 1
        else:
            print(f'{YELLOW}  ⚠ {label} (may be OK){NC}')
    sys.exit(import_errors)
except json.JSONDecodeError:
    print(f'{RED}Error: Could not parse import check results{NC}', file=sys.stderr)
    sys.exit(1)
" 2>&1
    IMPORT_ERRORS=$?
else
    echo -e "${RED}  ✗ Import check failed${NC}"
    echo "$CHECK_RESULT"
    IMPORT_ERRORS=1
fi

if [ $IMPORT_ERRORS -gt 0 ]; then
    echo ""
    echo -e "${RED}Error: $IMPORT_ERRORS import(s) failed. Please check the errors above.${NC}"
    exit 1
fi

echo ""

# Provider configuration - use associative arrays (Bash 4+) or indexed arrays (Bash 3.2)
if [ "$USE_ASSOC_ARRAYS" = true ]; then
    # Bash 4+ - use associative arrays (cleaner and more efficient)
    declare -A PROVIDER_NAMES=(
        ["ANTHROPIC_API_KEY"]="Anthropic (Claude)"
        ["OPENAI_API_KEY"]="OpenAI (GPT)"
        ["MINIMAX_API_KEY"]="MiniMax"
        ["GEMINI_API_KEY"]="Google Gemini"
        ["GOOGLE_API_KEY"]="Google AI"
        ["GROQ_API_KEY"]="Groq"
        ["CEREBRAS_API_KEY"]="Cerebras"
        ["OPENROUTER_API_KEY"]="OpenRouter"
        ["MISTRAL_API_KEY"]="Mistral"
        ["TOGETHER_API_KEY"]="Together AI"
        ["DEEPSEEK_API_KEY"]="DeepSeek"
    )

    declare -A PROVIDER_IDS=(
        ["ANTHROPIC_API_KEY"]="anthropic"
        ["OPENAI_API_KEY"]="openai"
        ["MINIMAX_API_KEY"]="minimax"
        ["GEMINI_API_KEY"]="gemini"
        ["GOOGLE_API_KEY"]="google"
        ["GROQ_API_KEY"]="groq"
        ["CEREBRAS_API_KEY"]="cerebras"
        ["OPENROUTER_API_KEY"]="openrouter"
        ["MISTRAL_API_KEY"]="mistral"
        ["TOGETHER_API_KEY"]="together"
        ["DEEPSEEK_API_KEY"]="deepseek"
    )

    declare -A DEFAULT_MODELS=(
        ["anthropic"]="claude-haiku-4-5-20251001"
        ["openai"]="gpt-5-mini"
        ["minimax"]="MiniMax-M2.5"
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
        ["anthropic:0"]="claude-haiku-4-5-20251001"
        ["anthropic:1"]="claude-sonnet-4-20250514"
        ["anthropic:2"]="claude-sonnet-4-5-20250929"
        ["anthropic:3"]="claude-opus-4-6"
        ["openai:0"]="gpt-5-mini"
        ["openai:1"]="gpt-5.2"
        ["gemini:0"]="gemini-3-flash-preview"
        ["gemini:1"]="gemini-3.1-pro-preview"
        ["groq:0"]="moonshotai/kimi-k2-instruct-0905"
        ["groq:1"]="openai/gpt-oss-120b"
        ["cerebras:0"]="zai-glm-4.7"
        ["cerebras:1"]="qwen3-235b-a22b-instruct-2507"
    )

    declare -A MODEL_CHOICES_LABEL=(
        ["anthropic:0"]="Haiku 4.5 - Fast + cheap (recommended)"
        ["anthropic:1"]="Sonnet 4 - Fast + capable"
        ["anthropic:2"]="Sonnet 4.5 - Best balance"
        ["anthropic:3"]="Opus 4.6 - Most capable"
        ["openai:0"]="GPT-5 Mini - Fast + cheap (recommended)"
        ["openai:1"]="GPT-5.2 - Most capable"
        ["gemini:0"]="Gemini 3 Flash - Fast (recommended)"
        ["gemini:1"]="Gemini 3.1 Pro - Best quality"
        ["groq:0"]="Kimi K2 - Best quality (recommended)"
        ["groq:1"]="GPT-OSS 120B - Fast reasoning"
        ["cerebras:0"]="ZAI-GLM 4.7 - Best quality (recommended)"
        ["cerebras:1"]="Qwen3 235B - Frontier reasoning"
    )

    declare -A MODEL_CHOICES_MAXTOKENS=(
        ["anthropic:0"]=8192
        ["anthropic:1"]=8192
        ["anthropic:2"]=16384
        ["anthropic:3"]=32768
        ["openai:0"]=16384
        ["openai:1"]=16384
        ["gemini:0"]=8192
        ["gemini:1"]=8192
        ["groq:0"]=8192
        ["groq:1"]=8192
        ["cerebras:0"]=8192
        ["cerebras:1"]=8192
    )

    # Max context tokens (input history budget) per model, based on actual context windows.
    # Leave ~10% headroom for system prompt and output tokens.
    declare -A MODEL_CHOICES_MAXCONTEXTTOKENS=(
        ["anthropic:0"]=180000   # Claude Haiku 4.5 — 200k context window
        ["anthropic:1"]=180000   # Claude Sonnet 4 — 200k context window
        ["anthropic:2"]=180000   # Claude Sonnet 4.5 — 200k context window
        ["anthropic:3"]=180000   # Claude Opus 4.6 — 200k context window
        ["openai:0"]=120000      # GPT-5 Mini — 128k context window
        ["openai:1"]=120000      # GPT-5.2 — 128k context window
        ["gemini:0"]=900000      # Gemini 3 Flash — 1M context window
        ["gemini:1"]=900000      # Gemini 3.1 Pro — 1M context window
        ["groq:0"]=120000        # Kimi K2 — 128k context window
        ["groq:1"]=120000        # GPT-OSS 120B — 128k context window
        ["cerebras:0"]=120000    # ZAI-GLM 4.7 — 128k context window
        ["cerebras:1"]=120000    # Qwen3 235B — 128k context window
    )

    declare -A MODEL_CHOICES_COUNT=(
        ["anthropic"]=4
        ["openai"]=2
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

    get_model_choice_maxcontexttokens() {
        echo "${MODEL_CHOICES_MAXCONTEXTTOKENS[$1:$2]}"
    }
else
    # Bash 3.2 - use parallel indexed arrays
    PROVIDER_ENV_VARS=(ANTHROPIC_API_KEY OPENAI_API_KEY MINIMAX_API_KEY GEMINI_API_KEY GOOGLE_API_KEY GROQ_API_KEY CEREBRAS_API_KEY OPENROUTER_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY DEEPSEEK_API_KEY)
    PROVIDER_DISPLAY_NAMES=("Anthropic (Claude)" "OpenAI (GPT)" "MiniMax" "Google Gemini" "Google AI" "Groq" "Cerebras" "OpenRouter" "Mistral" "Together AI" "DeepSeek")
    PROVIDER_ID_LIST=(anthropic openai minimax gemini google groq cerebras openrouter mistral together deepseek)

    # Default models by provider id (parallel arrays)
    MODEL_PROVIDER_IDS=(anthropic openai minimax gemini groq cerebras mistral together_ai deepseek)
    MODEL_DEFAULTS=("claude-haiku-4-5-20251001" "gpt-5-mini" "MiniMax-M2.5" "gemini-3-flash-preview" "moonshotai/kimi-k2-instruct-0905" "zai-glm-4.7" "mistral-large-latest" "meta-llama/Llama-3.3-70B-Instruct-Turbo" "deepseek-chat")

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
    # Provider order: anthropic(4), openai(2), gemini(2), groq(2), cerebras(2)
    MC_PROVIDERS=(anthropic anthropic anthropic anthropic openai openai gemini gemini groq groq cerebras cerebras)
    MC_IDS=("claude-haiku-4-5-20251001" "claude-sonnet-4-20250514" "claude-sonnet-4-5-20250929" "claude-opus-4-6" "gpt-5-mini" "gpt-5.2" "gemini-3-flash-preview" "gemini-3.1-pro-preview" "moonshotai/kimi-k2-instruct-0905" "openai/gpt-oss-120b" "zai-glm-4.7" "qwen3-235b-a22b-instruct-2507")
    MC_LABELS=("Haiku 4.5 - Fast + cheap (recommended)" "Sonnet 4 - Fast + capable" "Sonnet 4.5 - Best balance" "Opus 4.6 - Most capable" "GPT-5 Mini - Fast + cheap (recommended)" "GPT-5.2 - Most capable" "Gemini 3 Flash - Fast (recommended)" "Gemini 3.1 Pro - Best quality" "Kimi K2 - Best quality (recommended)" "GPT-OSS 120B - Fast reasoning" "ZAI-GLM 4.7 - Best quality (recommended)" "Qwen3 235B - Frontier reasoning")
    MC_MAXTOKENS=(8192 8192 16384 32768 16384 16384 8192 8192 8192 8192 8192 8192)
    # Max context tokens per model (same order as MC_PROVIDERS/MC_IDS above)
    # Based on actual context windows with ~10% headroom for system prompt + output.
    MC_MAXCONTEXTTOKENS=(180000 180000 180000 180000 120000 120000 900000 900000 120000 120000 120000 120000)

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

    # Helper: get model choice max_context_tokens by provider and index
    get_model_choice_maxcontexttokens() {
        local provider_id="$1"
        local idx="$2"
        local count=0
        local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$provider_id" ]; then
                if [ $count -eq "$idx" ]; then
                    echo "${MC_MAXCONTEXTTOKENS[$i]}"
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
            # Git Bash on Windows commonly starts as a login shell, so prefer
            # .bash_profile there when it already exists. On Unix-like shells,
            # keep the traditional .bashrc-first behavior.
            if [ -n "$MSYSTEM" ] || [ -n "$MINGW_PREFIX" ]; then
                if [ -f "$HOME/.bash_profile" ]; then
                    echo "$HOME/.bash_profile"
                elif [ -f "$HOME/.bashrc" ]; then
                    echo "$HOME/.bashrc"
                else
                    echo "$HOME/.profile"
                fi
            elif [ -f "$HOME/.bashrc" ]; then
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

# Normalize user-pasted OpenRouter model IDs:
# - trim whitespace
# - strip leading "openrouter/" if present
normalize_openrouter_model_id() {
    local raw="$1"
    # Trim leading/trailing whitespace
    raw="${raw#"${raw%%[![:space:]]*}"}"
    raw="${raw%"${raw##*[![:space:]]}"}"
    if [[ "$raw" =~ ^[Oo][Pp][Ee][Nn][Rr][Oo][Uu][Tt][Ee][Rr]/(.+)$ ]]; then
        raw="${BASH_REMATCH[1]}"
    fi
    printf '%s' "$raw"
}

# Prompt the user to choose a model for their selected provider.
# Sets SELECTED_MODEL, SELECTED_MAX_TOKENS, and SELECTED_MAX_CONTEXT_TOKENS.
prompt_model_selection() {
    local provider_id="$1"

    if [ "$provider_id" = "openrouter" ]; then
        local default_model=""
        if [ -n "$PREV_MODEL" ] && [ "$provider_id" = "$PREV_PROVIDER" ]; then
            default_model="$(normalize_openrouter_model_id "$PREV_MODEL")"
        fi
        echo ""
        echo -e "${BOLD}Enter your OpenRouter model id:${NC}"
        echo -e "  ${DIM}Paste from openrouter.ai (example: x-ai/grok-4.20-beta)${NC}"
        echo -e "  ${DIM}If calls fail with guardrail/privacy errors: openrouter.ai/settings/privacy${NC}"
        echo ""
        local input_model=""
        while true; do
            if [ -n "$default_model" ]; then
                read -r -p "Model id [$default_model]: " input_model || true
                input_model="${input_model:-$default_model}"
            else
                read -r -p "Model id: " input_model || true
            fi
            local normalized_model
            normalized_model="$(normalize_openrouter_model_id "$input_model")"
            if [ -n "$normalized_model" ]; then
                local openrouter_key=""
                if [ -n "${SELECTED_ENV_VAR:-}" ]; then
                    openrouter_key="${!SELECTED_ENV_VAR:-}"
                fi

                if [ -n "$openrouter_key" ]; then
                    local model_hc_result=""
                    local model_hc_valid=""
                    local model_hc_msg=""
                    local model_hc_canonical=""
                    local model_hc_base="${SELECTED_API_BASE:-https://openrouter.ai/api/v1}"
                    echo -n "  Verifying model id... "
                    model_hc_result="$(uv run python "$SCRIPT_DIR/scripts/check_llm_key.py" "openrouter" "$openrouter_key" "$model_hc_base" "$normalized_model" 2>/dev/null)" || true
                    model_hc_valid="$(echo "$model_hc_result" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('valid',''))" 2>/dev/null)" || true
                    model_hc_msg="$(echo "$model_hc_result" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('message',''))" 2>/dev/null)" || true
                    model_hc_canonical="$(echo "$model_hc_result" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('model',''))" 2>/dev/null)" || true
                    if [ "$model_hc_valid" = "True" ]; then
                        if [ -n "$model_hc_canonical" ]; then
                            normalized_model="$model_hc_canonical"
                        fi
                        echo -e "${GREEN}ok${NC}"
                    elif [ "$model_hc_valid" = "False" ]; then
                        echo -e "${RED}failed${NC}"
                        echo -e "  ${YELLOW}⚠ $model_hc_msg${NC}"
                        echo ""
                        continue
                    else
                        echo -e "${YELLOW}--${NC}"
                        echo -e "  ${DIM}Could not verify model id (network issue). Continuing with your selection.${NC}"
                    fi
                else
                    echo -e "  ${DIM}Skipping model verification (OpenRouter key not available in current shell).${NC}"
                fi

                SELECTED_MODEL="$normalized_model"
                SELECTED_MAX_TOKENS=8192
                SELECTED_MAX_CONTEXT_TOKENS=120000
                echo ""
                echo -e "${GREEN}⬢${NC} Model: ${DIM}$SELECTED_MODEL${NC}"
                return
            fi
            echo -e "${RED}Model id cannot be empty.${NC}"
        done
    fi

    local count
    count="$(get_model_choice_count "$provider_id")"

    if [ "$count" -eq 0 ]; then
        # No curated choices for this provider (e.g. Mistral, DeepSeek)
        SELECTED_MODEL="$(get_default_model "$provider_id")"
        SELECTED_MAX_TOKENS=8192
        SELECTED_MAX_CONTEXT_TOKENS=120000  # 128k context window (Mistral, DeepSeek, etc.)
        return
    fi

    if [ "$count" -eq 1 ]; then
        # Only one choice — auto-select
        SELECTED_MODEL="$(get_model_choice_id "$provider_id" 0)"
        SELECTED_MAX_TOKENS="$(get_model_choice_maxtokens "$provider_id" 0)"
        SELECTED_MAX_CONTEXT_TOKENS="$(get_model_choice_maxcontexttokens "$provider_id" 0)"
        return
    fi

    # Multiple choices — show menu
    echo ""
    echo -e "${BOLD}Select a model:${NC}"
    echo ""

    # Find default index from previous model (if same provider)
    local default_idx=""
    if [ -n "$PREV_MODEL" ] && [ "$provider_id" = "$PREV_PROVIDER" ]; then
        local j=0
        while [ $j -lt "$count" ]; do
            if [ "$(get_model_choice_id "$provider_id" "$j")" = "$PREV_MODEL" ]; then
                default_idx=$((j + 1))
                break
            fi
            j=$((j + 1))
        done
    fi

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
        if [ -n "$default_idx" ]; then
            read -r -p "Enter choice (1-$count) [$default_idx]: " choice || true
            choice="${choice:-$default_idx}"
        else
            read -r -p "Enter choice (1-$count): " choice || true
        fi
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$count" ]; then
            local idx=$((choice - 1))
            SELECTED_MODEL="$(get_model_choice_id "$provider_id" "$idx")"
            SELECTED_MAX_TOKENS="$(get_model_choice_maxtokens "$provider_id" "$idx")"
            SELECTED_MAX_CONTEXT_TOKENS="$(get_model_choice_maxcontexttokens "$provider_id" "$idx")"
            echo ""
            echo -e "${GREEN}⬢${NC} Model: ${DIM}$SELECTED_MODEL${NC}"
            return
        fi
        echo -e "${RED}Invalid choice. Please enter 1-$count${NC}"
    done
}

# Function to save configuration
# Args: provider_id env_var model max_tokens max_context_tokens [use_claude_code_sub] [api_base] [use_codex_sub] [use_antigravity_sub]
save_configuration() {
    local provider_id="$1"
    local env_var="$2"
    local model="$3"
    local max_tokens="$4"
    local max_context_tokens="$5"
    local use_claude_code_sub="${6:-}"
    local api_base="${7:-}"
    local use_codex_sub="${8:-}"
    local use_antigravity_sub="${9:-}"

    # Fallbacks if not provided
    if [ -z "$model" ]; then
        model="$(get_default_model "$provider_id")"
    fi
    if [ -z "$max_tokens" ]; then
        max_tokens=8192
    fi
    if [ -z "$max_context_tokens" ]; then
        max_context_tokens=120000
    fi

    uv run python - \
        "$provider_id" \
        "$env_var" \
        "$model" \
        "$max_tokens" \
        "$max_context_tokens" \
        "$use_claude_code_sub" \
        "$api_base" \
        "$use_codex_sub" \
        "$use_antigravity_sub" \
        "$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")" 2>/dev/null <<'PY'
import json
import sys
from pathlib import Path

(
    provider_id,
    env_var,
    model,
    max_tokens,
    max_context_tokens,
    use_claude_code_sub,
    api_base,
    use_codex_sub,
    use_antigravity_sub,
    created_at,
) = sys.argv[1:11]

cfg_path = Path.home() / ".hive" / "configuration.json"
cfg_path.parent.mkdir(parents=True, exist_ok=True)

try:
    with open(cfg_path, encoding="utf-8-sig") as f:
        config = json.load(f)
except (OSError, json.JSONDecodeError):
    config = {}

config["llm"] = {
    "provider": provider_id,
    "model": model,
    "max_tokens": int(max_tokens),
    "max_context_tokens": int(max_context_tokens),
}
if env_var:
    config["llm"]["api_key_env_var"] = env_var
config["created_at"] = created_at

if use_claude_code_sub == "true":
    config["llm"]["use_claude_code_subscription"] = True
    config["llm"].pop("api_key_env_var", None)
else:
    config["llm"].pop("use_claude_code_subscription", None)

if use_codex_sub == "true":
    config["llm"]["use_codex_subscription"] = True
    config["llm"].pop("api_key_env_var", None)
else:
    config["llm"].pop("use_codex_subscription", None)

if use_antigravity_sub == "true":
    config["llm"]["use_antigravity_subscription"] = True
    config["llm"].pop("api_key_env_var", None)
    # Store the Antigravity OAuth client secret so token refresh works
    # without hardcoding it in source code (read at runtime via config.py).
    import os as _os
    _secret = _os.environ.get("ANTIGRAVITY_CLIENT_SECRET") or ""
    if _secret:
        config["llm"]["antigravity_client_secret"] = _secret
    _client_id = _os.environ.get("ANTIGRAVITY_CLIENT_ID") or ""
    if _client_id:
        config["llm"]["antigravity_client_id"] = _client_id
else:
    config["llm"].pop("use_antigravity_subscription", None)
    config["llm"].pop("antigravity_client_secret", None)
    config["llm"].pop("antigravity_client_id", None)

if api_base:
    config["llm"]["api_base"] = api_base
else:
    config["llm"].pop("api_base", None)

tmp_path = cfg_path.with_name(cfg_path.name + ".tmp")
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
tmp_path.replace(cfg_path)
print(json.dumps(config, indent=2))
PY
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
SELECTED_MAX_TOKENS=8192 # Will hold the chosen max_tokens (output limit)
SELECTED_MAX_CONTEXT_TOKENS=120000 # Will hold the chosen max_context_tokens (input history budget)
SUBSCRIPTION_MODE=""    # "claude_code" | "codex" | "zai_code" | ""

# ── Credential detection (silent — just set flags) ───────────
CLAUDE_CRED_DETECTED=false
if command -v security &>/dev/null && security find-generic-password -s "Claude Code-credentials" &>/dev/null 2>&1; then
    CLAUDE_CRED_DETECTED=true
elif [ -f "$HOME/.claude/.credentials.json" ]; then
    CLAUDE_CRED_DETECTED=true
fi

CODEX_CRED_DETECTED=false
if command -v security &>/dev/null && security find-generic-password -s "Codex Auth" &>/dev/null 2>&1; then
    CODEX_CRED_DETECTED=true
elif [ -f "$HOME/.codex/auth.json" ]; then
    CODEX_CRED_DETECTED=true
fi

ZAI_CRED_DETECTED=false
if [ -n "${ZAI_API_KEY:-}" ]; then
    ZAI_CRED_DETECTED=true
fi

MINIMAX_CRED_DETECTED=false
if [ -n "${MINIMAX_API_KEY:-}" ]; then
    MINIMAX_CRED_DETECTED=true
fi

KIMI_CRED_DETECTED=false
if [ -f "$HOME/.kimi/config.toml" ]; then
    KIMI_CRED_DETECTED=true
elif [ -n "${KIMI_API_KEY:-}" ]; then
    KIMI_CRED_DETECTED=true
fi

HIVE_CRED_DETECTED=false
if [ -n "${HIVE_API_KEY:-}" ]; then
    HIVE_CRED_DETECTED=true
fi

ANTIGRAVITY_CRED_DETECTED=false
# Check native Antigravity IDE (macOS/Linux) SQLite state DB first
if [ -f "$HOME/Library/Application Support/Antigravity/User/globalStorage/state.vscdb" ]; then
    ANTIGRAVITY_CRED_DETECTED=true
elif [ -f "$HOME/.config/Antigravity/User/globalStorage/state.vscdb" ]; then
    ANTIGRAVITY_CRED_DETECTED=true
# Native OAuth credentials
elif [ -f "$HOME/.hive/antigravity-accounts.json" ]; then
    ANTIGRAVITY_CRED_DETECTED=true
fi

OLLAMA_DETECTED=false
if ollama list >/dev/null 2>&1; then
    OLLAMA_DETECTED=true
fi

# Detect API key providers
if [ "$USE_ASSOC_ARRAYS" = true ]; then
    for env_var in "${!PROVIDER_NAMES[@]}"; do
        if [ -n "${!env_var}" ]; then
            FOUND_PROVIDERS+=("$(get_provider_name "$env_var")")
            FOUND_ENV_VARS+=("$env_var")
        fi
    done
else
    for env_var in "${PROVIDER_ENV_VARS[@]}"; do
        if [ -n "${!env_var}" ]; then
            FOUND_PROVIDERS+=("$(get_provider_name "$env_var")")
            FOUND_ENV_VARS+=("$env_var")
        fi
    done
fi

# ── Read previous configuration (if any) ──────────────────────
PREV_PROVIDER=""
PREV_MODEL=""
PREV_ENV_VAR=""
PREV_SUB_MODE=""
if [ -f "$HIVE_CONFIG_FILE" ]; then
    eval "$(uv run python - 2>/dev/null <<'PY'
import json
from pathlib import Path

cfg_path = Path.home() / ".hive" / "configuration.json"
try:
    with open(cfg_path, encoding="utf-8-sig") as f:
        c = json.load(f)
    llm = c.get("llm", {})
    prov = llm.get("provider", "")
    mod = llm.get("model", "")
    env = llm.get("api_key_env_var", "")
    print(f"PREV_PROVIDER='{prov}'")
    print(f"PREV_MODEL='{mod}'")
    print(f"PREV_ENV_VAR='{env}'")
    sub = ""
    if llm.get("use_claude_code_subscription"):
        sub = "claude_code"
    elif llm.get("use_codex_subscription"):
        sub = "codex"
    elif llm.get("use_kimi_code_subscription"):
        sub = "kimi_code"
    elif llm.get("use_antigravity_subscription"):
        sub = "antigravity"
    elif llm.get("provider", "") == "minimax" or "api.minimax.io" in llm.get("api_base", ""):
        sub = "minimax_code"
    elif llm.get("provider", "") == "hive" or "adenhq.com" in llm.get("api_base", ""):
        sub = "hive_llm"
    elif "api.z.ai" in llm.get("api_base", ""):
        sub = "zai_code"
    print(f"PREV_SUB_MODE={sub}")
except Exception:
    pass
PY
)" || true
fi

# Compute default menu number from previous config (only if credential is still valid)
DEFAULT_CHOICE=""
if [ -n "$PREV_SUB_MODE" ] || [ -n "$PREV_PROVIDER" ]; then
    PREV_CRED_VALID=false
    case "$PREV_SUB_MODE" in
        claude_code) [ "$CLAUDE_CRED_DETECTED" = true ] && PREV_CRED_VALID=true ;;
        zai_code)    [ "$ZAI_CRED_DETECTED" = true ] && PREV_CRED_VALID=true ;;
        codex)       [ "$CODEX_CRED_DETECTED" = true ] && PREV_CRED_VALID=true ;;
        kimi_code)   [ "$KIMI_CRED_DETECTED" = true ] && PREV_CRED_VALID=true ;;
        hive_llm)    [ "$HIVE_CRED_DETECTED" = true ] && PREV_CRED_VALID=true ;;
        antigravity) [ "$ANTIGRAVITY_CRED_DETECTED" = true ] && PREV_CRED_VALID=true ;;
        *)
            # API key provider — check if the env var is set; ollama uses local runtime detection
            if [ "$PREV_PROVIDER" = "ollama" ]; then
                if [ "$OLLAMA_DETECTED" = true ]; then
                    PREV_CRED_VALID=true
                fi
            elif [ -n "$PREV_ENV_VAR" ] && [ -n "${!PREV_ENV_VAR}" ]; then
                PREV_CRED_VALID=true
            fi
            ;;
    esac

    if [ "$PREV_CRED_VALID" = true ]; then
        case "$PREV_SUB_MODE" in
            claude_code) DEFAULT_CHOICE=1 ;;
            zai_code)    DEFAULT_CHOICE=2 ;;
            codex)       DEFAULT_CHOICE=3 ;;
            minimax_code) DEFAULT_CHOICE=4 ;;
            kimi_code)   DEFAULT_CHOICE=5 ;;
            hive_llm)    DEFAULT_CHOICE=6 ;;
            antigravity) DEFAULT_CHOICE=7 ;;
        esac
        if [ -z "$DEFAULT_CHOICE" ]; then
            case "$PREV_PROVIDER" in
                anthropic) DEFAULT_CHOICE=8 ;;
                openai)    DEFAULT_CHOICE=9 ;;
                gemini)    DEFAULT_CHOICE=10 ;;
                groq)      DEFAULT_CHOICE=11 ;;
                cerebras)  DEFAULT_CHOICE=12 ;;
                openrouter) DEFAULT_CHOICE=13 ;;
                ollama)    DEFAULT_CHOICE=14 ;;
                minimax)   DEFAULT_CHOICE=4 ;;
                kimi)      DEFAULT_CHOICE=5 ;;
                hive)      DEFAULT_CHOICE=6 ;;
            esac
        fi
    fi
fi

HIVE_LLM_AVAILABLE="unknown"
if check_hive_llm_availability "quickstart"; then
    HIVE_LLM_AVAILABLE="yes"
elif [ $? -eq 1 ]; then
    HIVE_LLM_AVAILABLE="no"
fi

# ── Show unified provider selection menu ─────────────────────
echo -e "${BOLD}Select your default LLM provider:${NC}"
echo ""
if [ "$HIVE_LLM_AVAILABLE" = "yes" ]; then
    echo -e "${GREEN}⬢${NC} Hive LLM availability check: ${DIM}available${NC}"
elif [ "$HIVE_LLM_AVAILABLE" = "no" ]; then
    echo -e "${YELLOW}⬢${NC} Hive LLM availability check: ${DIM}currently unavailable${NC}"
else
    echo -e "${YELLOW}⬢${NC} Hive LLM availability check: ${DIM}could not verify${NC}"
fi
echo ""
echo -e "  ${CYAN}${BOLD}Subscription modes (no API key purchase needed):${NC}"

# 1) Claude Code
if [ "$CLAUDE_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}1)${NC} Claude Code Subscription  ${DIM}(use your Claude Max/Pro plan)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}1)${NC} Claude Code Subscription  ${DIM}(use your Claude Max/Pro plan)${NC}"
fi

# 2) ZAI Code
if [ "$ZAI_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}2)${NC} ZAI Code Subscription     ${DIM}(use your ZAI Code plan)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}2)${NC} ZAI Code Subscription     ${DIM}(use your ZAI Code plan)${NC}"
fi

# 3) Codex
if [ "$CODEX_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}3)${NC} OpenAI Codex Subscription  ${DIM}(use your Codex/ChatGPT Plus plan)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}3)${NC} OpenAI Codex Subscription  ${DIM}(use your Codex/ChatGPT Plus plan)${NC}"
fi

# 4) MiniMax
if [ "$MINIMAX_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}4)${NC} MiniMax Coding Key         ${DIM}(use your MiniMax coding key)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}4)${NC} MiniMax Coding Key         ${DIM}(use your MiniMax coding key)${NC}"
fi

# 5) Kimi Code
if [ "$KIMI_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}5)${NC} Kimi Code Subscription     ${DIM}(use your Kimi Code plan)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}5)${NC} Kimi Code Subscription     ${DIM}(use your Kimi Code plan)${NC}"
fi

# 6) Hive LLM
if [ "$HIVE_LLM_AVAILABLE" = "yes" ]; then
    HIVE_LLM_STATUS="${GREEN}(available)${NC}"
elif [ "$HIVE_LLM_AVAILABLE" = "no" ]; then
    HIVE_LLM_STATUS="${YELLOW}(unavailable)${NC}"
else
    HIVE_LLM_STATUS="${YELLOW}(status unknown)${NC}"
fi

if [ "$HIVE_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}6)${NC} Hive LLM                   ${DIM}(use your Hive API key)${NC}  $HIVE_LLM_STATUS  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}6)${NC} Hive LLM                   ${DIM}(use your Hive API key)${NC}  $HIVE_LLM_STATUS"
fi

# 7) Antigravity
if [ "$ANTIGRAVITY_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}7)${NC} Antigravity Subscription  ${DIM}(use your Google/Gemini plan)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}7)${NC} Antigravity Subscription  ${DIM}(use your Google/Gemini plan)${NC}"
fi

echo ""
echo -e "  ${CYAN}${BOLD}API key providers:${NC}"

# 8-13) API key providers — show (credential detected) if key already set
PROVIDER_MENU_ENVS=(ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GROQ_API_KEY CEREBRAS_API_KEY OPENROUTER_API_KEY)
PROVIDER_MENU_NAMES=("Anthropic (Claude) - Recommended" "OpenAI (GPT)" "Google Gemini - Free tier available" "Groq - Fast, free tier" "Cerebras - Fast, free tier" "OpenRouter - Bring any OpenRouter model")
for idx in "${!PROVIDER_MENU_ENVS[@]}"; do
    num=$((idx + 8))
    env_var="${PROVIDER_MENU_ENVS[$idx]}"
    if [ -n "${!env_var}" ]; then
        echo -e "  ${CYAN}$num)${NC} ${PROVIDER_MENU_NAMES[$idx]}  ${GREEN}(credential detected)${NC}"
    else
        echo -e "  ${CYAN}$num)${NC} ${PROVIDER_MENU_NAMES[$idx]}"
    fi
done

# 14) Local (Ollama) — no API key needed
if [ "$OLLAMA_DETECTED" = true ]; then
    echo -e "  ${CYAN}14)${NC} Local (Ollama) - No API key needed  ${GREEN}(ollama detected)${NC}"
else
    echo -e "  ${CYAN}14)${NC} Local (Ollama) - No API key needed"
fi

SKIP_CHOICE=$((8 + ${#PROVIDER_MENU_ENVS[@]} + 1))
echo -e "  ${CYAN}$SKIP_CHOICE)${NC} Skip for now"
echo ""

if [ -n "$DEFAULT_CHOICE" ]; then
    echo -e "  ${DIM}Previously configured: ${PREV_PROVIDER}/${PREV_MODEL}. Press Enter to keep.${NC}"
    echo ""
fi

while true; do
    if [ -n "$DEFAULT_CHOICE" ]; then
        read -r -p "Enter choice (1-$SKIP_CHOICE) [$DEFAULT_CHOICE]: " choice || true
        choice="${choice:-$DEFAULT_CHOICE}"
    else
        read -r -p "Enter choice (1-$SKIP_CHOICE): " choice || true
    fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$SKIP_CHOICE" ]; then
        break
    fi
    echo -e "${RED}Invalid choice. Please enter 1-$SKIP_CHOICE${NC}"
done

case $choice in
    1)
        # Claude Code Subscription
        if [ "$CLAUDE_CRED_DETECTED" = false ]; then
            echo ""
            echo -e "${YELLOW}  ~/.claude/.credentials.json not found.${NC}"
            echo -e "  Run ${CYAN}claude${NC} first to authenticate with your Claude subscription,"
            echo -e "  then run this quickstart again."
            echo ""
            exit 1
        else
            SUBSCRIPTION_MODE="claude_code"
            SELECTED_PROVIDER_ID="anthropic"
            SELECTED_MODEL="claude-opus-4-6"
            SELECTED_MAX_TOKENS=32768
            SELECTED_MAX_CONTEXT_TOKENS=960000  # Claude — 1M context window
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
        SELECTED_MAX_CONTEXT_TOKENS=180000  # GLM-5 — 200k context window
        PROVIDER_NAME="ZAI"
        echo ""
        echo -e "${GREEN}⬢${NC} Using ZAI Code subscription"
        echo -e "  ${DIM}Model: glm-5 | API: api.z.ai${NC}"
        ;;
    3)
        # OpenAI Codex Subscription
        if [ "$CODEX_CRED_DETECTED" = false ]; then
            echo ""
            echo -e "${YELLOW}  Codex credentials not found. Starting OAuth login...${NC}"
            echo ""
            if uv run python "$SCRIPT_DIR/core/codex_oauth.py"; then
                CODEX_CRED_DETECTED=true
            else
                echo ""
                echo -e "${RED}  OAuth login failed or was cancelled.${NC}"
                echo ""
                echo -e "  To authenticate manually, visit:"
                echo -e "  ${CYAN}https://auth.openai.com/authorize?client_id=app_EMoamEEZ73f0CkXaXp7hrann&response_type=code&redirect_uri=http://localhost:1455/auth/callback&scope=openid%20profile%20email%20offline_access${NC}"
                echo ""
                echo -e "  Or run ${CYAN}codex${NC} to authenticate, then run this quickstart again."
                echo ""
                SELECTED_PROVIDER_ID=""
            fi
        fi
        if [ "$CODEX_CRED_DETECTED" = true ]; then
            SUBSCRIPTION_MODE="codex"
            SELECTED_PROVIDER_ID="openai"
            SELECTED_MODEL="gpt-5.3-codex"
            SELECTED_MAX_TOKENS=16384
            SELECTED_MAX_CONTEXT_TOKENS=120000  # GPT Codex — 128k context window
            echo ""
            echo -e "${GREEN}⬢${NC} Using OpenAI Codex subscription"
        fi
        ;;
    4)
        # MiniMax Coding Key
        SUBSCRIPTION_MODE="minimax_code"
        SELECTED_ENV_VAR="MINIMAX_API_KEY"
        SELECTED_PROVIDER_ID="minimax"
        SELECTED_MODEL="MiniMax-M2.5"
        SELECTED_MAX_TOKENS=32768
        SELECTED_MAX_CONTEXT_TOKENS=900000  # MiniMax M2.5 — 1M context window
        SELECTED_API_BASE="https://api.minimax.io/v1"
        PROVIDER_NAME="MiniMax"
        SIGNUP_URL="https://platform.minimax.io/user-center/basic-information/interface-key"
        echo ""
        echo -e "${GREEN}⬢${NC} Using MiniMax coding key"
        echo -e "  ${DIM}Model: MiniMax-M2.5 | API: api.minimax.io${NC}"
        ;;
    5)
        # Kimi Code Subscription
        SUBSCRIPTION_MODE="kimi_code"
        SELECTED_PROVIDER_ID="kimi"
        SELECTED_ENV_VAR="KIMI_API_KEY"
        SELECTED_MODEL="kimi-k2.5"
        SELECTED_MAX_TOKENS=32768
        SELECTED_MAX_CONTEXT_TOKENS=240000  # Kimi K2.5 — 256k context window
        SELECTED_API_BASE="https://api.kimi.com/coding"
        PROVIDER_NAME="Kimi"
        SIGNUP_URL="https://www.kimi.com/code"
        echo ""
        echo -e "${GREEN}⬢${NC} Using Kimi Code subscription"
        echo -e "  ${DIM}Model: kimi-k2.5 | API: api.kimi.com/coding${NC}"
        ;;
    6)
        # Hive LLM
        SUBSCRIPTION_MODE="hive_llm"
        SELECTED_PROVIDER_ID="hive"
        SELECTED_ENV_VAR="HIVE_API_KEY"
        SELECTED_MAX_TOKENS=32768
        SELECTED_MAX_CONTEXT_TOKENS=180000
        SELECTED_API_BASE="$HIVE_LLM_ENDPOINT"
        PROVIDER_NAME="Hive"
        SIGNUP_URL="https://discord.com/invite/hQdU7QDkgR"
        echo ""
        echo -e "${GREEN}⬢${NC} Using Hive LLM"
        echo ""
        echo -e "  Select a model:"
        echo -e "  ${CYAN}1)${NC} queen              ${DIM}(default — Hive flagship)${NC}"
        echo -e "  ${CYAN}2)${NC} kimi-2.5"
        echo -e "  ${CYAN}3)${NC} GLM-5"
        echo ""
        read -r -p "  Enter model choice (1-3) [1]: " hive_model_choice || true
        hive_model_choice="${hive_model_choice:-1}"
        case "$hive_model_choice" in
            2) SELECTED_MODEL="kimi-2.5" ;;
            3) SELECTED_MODEL="GLM-5" ;;
            *) SELECTED_MODEL="queen" ;;
        esac
        echo -e "  ${DIM}Model: $SELECTED_MODEL | API: ${HIVE_LLM_ENDPOINT}${NC}"
        ;;
    7)
        # Antigravity Subscription
        if [ "$ANTIGRAVITY_CRED_DETECTED" = false ]; then
            echo ""
            echo -e "${CYAN}  Setting up Antigravity authentication...${NC}"
            echo ""
            echo -e "  ${YELLOW}A browser window will open for Google OAuth.${NC}"
            echo -e "  Sign in with your Google account that has Antigravity access."
            echo ""

            # Run native OAuth flow
            if uv run python "$SCRIPT_DIR/core/antigravity_auth.py" auth account add; then
                # Re-detect credentials
                if [ -f "$HOME/.hive/antigravity-accounts.json" ]; then
                    ANTIGRAVITY_CRED_DETECTED=true
                fi
            fi

            if [ "$ANTIGRAVITY_CRED_DETECTED" = false ]; then
                echo ""
                echo -e "${RED}  Authentication failed or was cancelled.${NC}"
                echo ""
                SELECTED_PROVIDER_ID=""
            fi
        fi

        if [ "$ANTIGRAVITY_CRED_DETECTED" = true ]; then
            SUBSCRIPTION_MODE="antigravity"
            SELECTED_PROVIDER_ID="openai"
            SELECTED_MODEL="gemini-3-flash"
            SELECTED_MAX_TOKENS=32768
            SELECTED_MAX_CONTEXT_TOKENS=1000000  # Gemini 3 Flash — 1M context window
            echo ""
            echo -e "${YELLOW}  ⚠ Using Antigravity can technically cause your account suspension. Please use at your own risk.${NC}"
            echo ""
            echo -e "${GREEN}⬢${NC} Using Antigravity subscription"
            echo -e "  ${DIM}Model: gemini-3-flash | Direct OAuth (no proxy required)${NC}"
        fi
        ;;
    8)
        SELECTED_ENV_VAR="ANTHROPIC_API_KEY"
        SELECTED_PROVIDER_ID="anthropic"
        PROVIDER_NAME="Anthropic"
        SIGNUP_URL="https://console.anthropic.com/settings/keys"
        ;;
    9)
        SELECTED_ENV_VAR="OPENAI_API_KEY"
        SELECTED_PROVIDER_ID="openai"
        PROVIDER_NAME="OpenAI"
        SIGNUP_URL="https://platform.openai.com/api-keys"
        ;;
    10)
        SELECTED_ENV_VAR="GEMINI_API_KEY"
        SELECTED_PROVIDER_ID="gemini"
        PROVIDER_NAME="Google Gemini"
        SIGNUP_URL="https://aistudio.google.com/apikey"
        ;;
    11)
        SELECTED_ENV_VAR="GROQ_API_KEY"
        SELECTED_PROVIDER_ID="groq"
        PROVIDER_NAME="Groq"
        SIGNUP_URL="https://console.groq.com/keys"
        ;;
    12)
        SELECTED_ENV_VAR="CEREBRAS_API_KEY"
        SELECTED_PROVIDER_ID="cerebras"
        PROVIDER_NAME="Cerebras"
        SIGNUP_URL="https://cloud.cerebras.ai/"
        ;;
    13)
        SELECTED_ENV_VAR="OPENROUTER_API_KEY"
        SELECTED_PROVIDER_ID="openrouter"
        SELECTED_API_BASE="https://openrouter.ai/api/v1"
        PROVIDER_NAME="OpenRouter"
        SIGNUP_URL="https://openrouter.ai/keys"
        ;;
    14)
        # Local (Ollama) — no API key; pick model from ollama list
        if [ "$OLLAMA_DETECTED" != true ]; then
            echo ""
            echo -e "${YELLOW}Ollama depends on a local Ollama server, but 'ollama list' failed.${NC}"
            echo -e "  Please install Ollama (https://ollama.com) and start the server,"
            echo -e "  then run this quickstart again."
            echo ""
            exit 1
        fi
        SELECTED_PROVIDER_ID="ollama"
        SELECTED_ENV_VAR=""
        SELECTED_MAX_TOKENS=8192
        SELECTED_MAX_CONTEXT_TOKENS=16384
        OLLAMA_MODELS=()
        while IFS= read -r line; do
            [ -n "$line" ] && OLLAMA_MODELS+=("$line")
        done < <(ollama list 2>/dev/null | tail -n +2 | awk '{print $1}')
        if [ ${#OLLAMA_MODELS[@]} -gt 0 ]; then
            echo ""
            echo -e "${BOLD}Select an Ollama model:${NC}"
            echo ""
            for idx in "${!OLLAMA_MODELS[@]}"; do
                num=$((idx + 1))
                echo -e "  ${CYAN}$num)${NC} ${OLLAMA_MODELS[$idx]}"
            done
            echo ""
            while true; do
                read -r -p "Enter choice (1-${#OLLAMA_MODELS[@]}): " model_choice
                if [[ "$model_choice" =~ ^[0-9]+$ ]] && [ "$model_choice" -ge 1 ] && [ "$model_choice" -le ${#OLLAMA_MODELS[@]} ]; then
                    SELECTED_MODEL="${OLLAMA_MODELS[$((model_choice - 1))]}"
                    SELECTED_API_BASE="http://localhost:11434"
                    break
                fi
                echo -e "${RED}Invalid choice. Please enter 1-${#OLLAMA_MODELS[@]}${NC}"
            done
            echo ""
            echo -e "${GREEN}⬢${NC} Using Ollama with model ${DIM}$SELECTED_MODEL${NC}"
            echo -e "${YELLOW}  ⚠ Note: The framework uses a ~9,500 token system prompt and requires strong tool use.${NC}"
            echo -e "${YELLOW}    For best results, use models like qwen2.5:72b+ or mistral-large.${NC}"
            echo ""
        else
            echo ""
            echo -e "${RED}No Ollama models found.${NC}"
            echo -e "  Please open another terminal, run ${CYAN}ollama pull llama3${NC} (or another model),"
            echo -e "  and then run this quickstart again."
            echo ""
            exit 1
        fi
        ;;
    "$SKIP_CHOICE")
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

# For API-key providers: prompt for key (allow replacement if already set)
if { [ -z "$SUBSCRIPTION_MODE" ] || [ "$SUBSCRIPTION_MODE" = "minimax_code" ] || [ "$SUBSCRIPTION_MODE" = "kimi_code" ] || [ "$SUBSCRIPTION_MODE" = "hive_llm" ]; } && [ -n "$SELECTED_ENV_VAR" ]; then
    while true; do
        CURRENT_KEY="${!SELECTED_ENV_VAR}"
        if [ -n "$CURRENT_KEY" ]; then
            # Key exists — offer to keep or replace
            MASKED_KEY="${CURRENT_KEY:0:4}...${CURRENT_KEY: -4}"
            echo ""
            echo -e "  ${GREEN}⬢${NC} Current key: ${DIM}$MASKED_KEY${NC}"
            read -r -p "  Press Enter to keep, or paste a new key to replace: " API_KEY
        else
            # No key — prompt for one
            echo ""
            echo -e "Get your API key from: ${CYAN}$SIGNUP_URL${NC}"
            echo ""
            read -r -p "Paste your $PROVIDER_NAME API key (or press Enter to skip): " API_KEY
        fi

        if [ -n "$API_KEY" ]; then
            # Remove old export line(s) for this env var from shell rc, then append new
            sed -i.bak "/^export ${SELECTED_ENV_VAR}=/d" "$SHELL_RC_FILE" && rm -f "${SHELL_RC_FILE}.bak"
            echo "" >> "$SHELL_RC_FILE"
            echo "# Hive Agent Framework - $PROVIDER_NAME API key" >> "$SHELL_RC_FILE"
            echo "export $SELECTED_ENV_VAR=\"$API_KEY\"" >> "$SHELL_RC_FILE"
            export "$SELECTED_ENV_VAR=$API_KEY"
            echo ""
            echo -e "${GREEN}⬢${NC} API key saved to $SHELL_RC_FILE"
            # Health check the new key
            echo -n "  Verifying API key... "
            if [ -n "${SELECTED_API_BASE:-}" ]; then
                HC_RESULT=$(uv run python "$SCRIPT_DIR/scripts/check_llm_key.py" "$SELECTED_PROVIDER_ID" "$API_KEY" "$SELECTED_API_BASE" 2>/dev/null) || true
            else
                HC_RESULT=$(uv run python "$SCRIPT_DIR/scripts/check_llm_key.py" "$SELECTED_PROVIDER_ID" "$API_KEY" 2>/dev/null) || true
            fi
            HC_VALID=$(echo "$HC_RESULT" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('valid',''))" 2>/dev/null) || true
            HC_MSG=$(echo "$HC_RESULT" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('message',''))" 2>/dev/null) || true
            if [ "$HC_VALID" = "True" ]; then
                echo -e "${GREEN}ok${NC}"
                break
            elif [ "$HC_VALID" = "False" ]; then
                echo -e "${RED}failed${NC}"
                echo -e "  ${YELLOW}⚠ $HC_MSG${NC}"
                # Undo the save so the user can retry cleanly
                sed -i.bak "/^export ${SELECTED_ENV_VAR}=/d" "$SHELL_RC_FILE" && rm -f "${SHELL_RC_FILE}.bak"
                # Remove the comment line we just added
                sed -i.bak "/^# Hive Agent Framework - $PROVIDER_NAME API key$/d" "$SHELL_RC_FILE" && rm -f "${SHELL_RC_FILE}.bak"
                unset "$SELECTED_ENV_VAR"
                echo ""
                read -r -p "  Press Enter to try again: " _
                # Loop back to key prompt
            else
                echo -e "${YELLOW}--${NC}"
                echo -e "  ${DIM}Could not verify key (network issue). The key has been saved.${NC}"
                break
            fi
        elif [ -z "$CURRENT_KEY" ]; then
            # No existing key and user skipped — abort provider
            echo ""
            echo -e "${YELLOW}Skipped.${NC} Add your API key to $SHELL_RC_FILE when ready."
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
            break
        else
            # User pressed Enter with existing key — keep it, proceed normally
            break
        fi
    done
fi

# For ZAI subscription: prompt for API key (allow replacement if already set)
if [ "$SUBSCRIPTION_MODE" = "zai_code" ]; then
    while true; do
        if [ "$ZAI_CRED_DETECTED" = true ] && [ -n "$ZAI_API_KEY" ]; then
            # Key exists — offer to keep or replace
            MASKED_KEY="${ZAI_API_KEY:0:4}...${ZAI_API_KEY: -4}"
            echo ""
            echo -e "  ${GREEN}⬢${NC} Current ZAI key: ${DIM}$MASKED_KEY${NC}"
            read -r -p "  Press Enter to keep, or paste a new key to replace: " API_KEY
        else
            # No key — prompt for one
            echo ""
            read -r -p "Paste your ZAI API key (or press Enter to skip): " API_KEY
        fi

        if [ -n "$API_KEY" ]; then
            sed -i.bak "/^export ZAI_API_KEY=/d" "$SHELL_RC_FILE" && rm -f "${SHELL_RC_FILE}.bak"
            echo "" >> "$SHELL_RC_FILE"
            echo "# Hive Agent Framework - ZAI Code subscription API key" >> "$SHELL_RC_FILE"
            echo "export ZAI_API_KEY=\"$API_KEY\"" >> "$SHELL_RC_FILE"
            export ZAI_API_KEY="$API_KEY"
            echo ""
            echo -e "${GREEN}⬢${NC} ZAI API key saved to $SHELL_RC_FILE"
            # Health check the new key
            echo -n "  Verifying ZAI API key... "
            HC_RESULT=$(uv run python "$SCRIPT_DIR/scripts/check_llm_key.py" "zai" "$API_KEY" "https://api.z.ai/api/coding/paas/v4" 2>/dev/null) || true
            HC_VALID=$(echo "$HC_RESULT" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('valid',''))" 2>/dev/null) || true
            HC_MSG=$(echo "$HC_RESULT" | $PYTHON_CMD -c "import json,sys; print(json.loads(sys.stdin.read()).get('message',''))" 2>/dev/null) || true
            if [ "$HC_VALID" = "True" ]; then
                echo -e "${GREEN}ok${NC}"
                break
            elif [ "$HC_VALID" = "False" ]; then
                echo -e "${RED}failed${NC}"
                echo -e "  ${YELLOW}⚠ $HC_MSG${NC}"
                # Undo the save so the user can retry cleanly
                sed -i.bak "/^export ZAI_API_KEY=/d" "$SHELL_RC_FILE" && rm -f "${SHELL_RC_FILE}.bak"
                sed -i.bak "/^# Hive Agent Framework - ZAI Code subscription API key$/d" "$SHELL_RC_FILE" && rm -f "${SHELL_RC_FILE}.bak"
                unset ZAI_API_KEY
                ZAI_CRED_DETECTED=false
                echo ""
                read -r -p "  Press Enter to try again: " _
                # Loop back to key prompt
            else
                echo -e "${YELLOW}--${NC}"
                echo -e "  ${DIM}Could not verify key (network issue). The key has been saved.${NC}"
                break
            fi
        elif [ "$ZAI_CRED_DETECTED" = false ] || [ -z "$ZAI_API_KEY" ]; then
            # No existing key and user skipped — abort provider
            echo ""
            echo -e "${YELLOW}Skipped.${NC} Add your ZAI API key to $SHELL_RC_FILE when ready:"
            echo -e "  ${CYAN}echo 'export ZAI_API_KEY=\"your-key\"' >> $SHELL_RC_FILE${NC}"
            SELECTED_ENV_VAR=""
            SELECTED_PROVIDER_ID=""
            SUBSCRIPTION_MODE=""
            break
        else
            # User pressed Enter with existing key — keep it, proceed normally
            break
        fi
    done
fi

# Prompt for model if not already selected (manual provider path)
if [ -n "$SELECTED_PROVIDER_ID" ] && [ -z "$SELECTED_MODEL" ]; then
    prompt_model_selection "$SELECTED_PROVIDER_ID"
fi

# Save configuration if a provider was selected
if [ -n "$SELECTED_PROVIDER_ID" ]; then
    echo ""
    echo -n "  Saving configuration... "
    SAVE_OK=true
    if [ "$SUBSCRIPTION_MODE" = "claude_code" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "true" "" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "codex" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "" "true" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "antigravity" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "" "" "true" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "zai_code" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "https://api.z.ai/api/coding/paas/v4" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "minimax_code" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "kimi_code" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "hive_llm" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SELECTED_PROVIDER_ID" = "openrouter" ]; then
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SELECTED_PROVIDER_ID" = "ollama" ]; then
        # Pass api_base explicitly — LiteLLM requires this to route ollama/* models
        # to the local Ollama server instead of trying to reach a remote endpoint.
        save_configuration "ollama" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "http://localhost:11434" > /dev/null || SAVE_OK=false
    else
        save_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" > /dev/null || SAVE_OK=false
    fi
    if [ "$SAVE_OK" = false ]; then
        echo -e "${RED}failed${NC}"
        echo -e "${YELLOW}  Could not write ~/.hive/configuration.json. Please rerun quickstart.${NC}"
        exit 1
    fi
    echo -e "${GREEN}⬢${NC}"
    echo -e "  ${DIM}~/.hive/configuration.json${NC}"
fi

echo ""

# ============================================================
# Browser Automation (GCU) — always enabled
# ============================================================

echo -e "${GREEN}⬢${NC} Browser automation enabled"

# Patch gcu_enabled into configuration.json
if [ -f "$HIVE_CONFIG_FILE" ]; then
    if ! uv run python - <<'PY'
import json
from pathlib import Path

cfg_path = Path.home() / ".hive" / "configuration.json"
with open(cfg_path, encoding="utf-8-sig") as f:
    config = json.load(f)
config["gcu_enabled"] = True
tmp_path = cfg_path.with_name(cfg_path.name + ".tmp")
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
tmp_path.replace(cfg_path)
PY
    then
        echo -e "${RED}failed${NC}"
        echo -e "${YELLOW}  Could not update ~/.hive/configuration.json with browser automation settings.${NC}"
        exit 1
    fi
else
    if ! uv run python - "$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")" <<'PY'
import json
import sys
from pathlib import Path

cfg_path = Path.home() / ".hive" / "configuration.json"
cfg_path.parent.mkdir(parents=True, exist_ok=True)
config = {
    "gcu_enabled": True,
    "created_at": sys.argv[1],
}
with open(cfg_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
PY
    then
        echo -e "${RED}failed${NC}"
        echo -e "${YELLOW}  Could not create ~/.hive/configuration.json for browser automation settings.${NC}"
        exit 1
    fi
fi

echo ""

# ============================================================
# Step 4: Initialize Credential Store
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 4: Initializing credential store...${NC}"
echo ""
echo -e "${DIM}The credential store encrypts API keys and secrets for your agents.${NC}"
echo ""

HIVE_CRED_DIR="$HOME/.hive/credentials"

HIVE_KEY_FILE="$HOME/.hive/secrets/credential_key"

# Check if HIVE_CREDENTIAL_KEY already exists (from env, file, or shell rc)
if [ -n "$HIVE_CREDENTIAL_KEY" ]; then
    echo -e "${GREEN}  ✓ HIVE_CREDENTIAL_KEY already set${NC}"
elif [ -f "$HIVE_KEY_FILE" ]; then
    HIVE_CREDENTIAL_KEY=$(cat "$HIVE_KEY_FILE")
    export HIVE_CREDENTIAL_KEY
    echo -e "${GREEN}  ✓ HIVE_CREDENTIAL_KEY loaded from $HIVE_KEY_FILE${NC}"
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

        # Save to dedicated secrets file (chmod 600)
        mkdir -p "$(dirname "$HIVE_KEY_FILE")"
        chmod 700 "$(dirname "$HIVE_KEY_FILE")"
        echo -n "$GENERATED_KEY" > "$HIVE_KEY_FILE"
        chmod 600 "$HIVE_KEY_FILE"
        export HIVE_CREDENTIAL_KEY="$GENERATED_KEY"

        echo -e "${GREEN}  ✓ Encryption key saved to $HIVE_KEY_FILE${NC}"
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
# Step 4b: Load browser extension into Chrome (one-time setup)
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Setting up browser extension...${NC}"
echo ""

EXTENSION_PATH="$SCRIPT_DIR/tools/browser-extension"
CHROME_BIN=""
CHROME_LAUNCHED=false

# Find Chrome binary
for _bin in "google-chrome" "google-chrome-stable" "chromium" "chromium-browser" "microsoft-edge" "microsoft-edge-stable"; do
    if command -v "$_bin" &> /dev/null; then
        CHROME_BIN="$_bin"
        break
    fi
done
# macOS
if [ -z "$CHROME_BIN" ]; then
    for _path in \
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"; do
        if [ -e "$_path" ]; then
            CHROME_BIN="$_path"
            break
        fi
    done
fi

if [ ! -d "$EXTENSION_PATH" ]; then
    echo -e "${YELLOW}  Extension not found at $EXTENSION_PATH — skipping${NC}"
elif [ -z "$CHROME_BIN" ]; then
    echo -e "${YELLOW}  Chrome not found — skipping${NC}"
    echo -e "${DIM}    Install Chrome, then load: $EXTENSION_PATH via chrome://extensions${NC}"
else
    # Copy path to clipboard (best-effort)
    if command -v xclip &> /dev/null; then
        printf '%s' "$EXTENSION_PATH" | xclip -selection clipboard 2>/dev/null && _copied=true
    elif command -v xsel &> /dev/null; then
        printf '%s' "$EXTENSION_PATH" | xsel --clipboard --input 2>/dev/null && _copied=true
    elif command -v pbcopy &> /dev/null; then
        printf '%s' "$EXTENSION_PATH" | pbcopy 2>/dev/null && _copied=true
    fi

    read -r -p "  Press Enter when you are ready to set up the Chrome extension... " _dummy || true
    echo ""

    # Open setup guide in default browser
    SETUP_URL="file://$SCRIPT_DIR/docs/browser-extension-setup.html?path=$(printf '%s' "$EXTENSION_PATH" | sed 's/ /%20/g')"
    echo -e "  Opening browser extension setup guide..."
    if [ "${_copied:-false}" = "true" ]; then
        echo -e "  ${DIM}(extension path copied to clipboard — paste it in the folder picker)${NC}"
    fi
    if [[ "$OSTYPE" == darwin* ]]; then
        open "$SETUP_URL" 2>/dev/null
    elif command -v xdg-open &> /dev/null; then
        xdg-open "$SETUP_URL" > /dev/null 2>&1 &
    elif command -v wslview &> /dev/null; then
        wslview "$SETUP_URL" > /dev/null 2>&1 &
    else
        echo -e "  ${DIM}Could not open browser automatically. Visit:${NC}"
        echo -e "  ${BOLD}$SETUP_URL${NC}"
    fi

    echo ""
    read -r -p "  Press Enter once you've finished the extension setup... " _dummy || true
    CHROME_LAUNCHED=true
fi

echo ""

# ============================================================
# Step 5: Verify Setup
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 5: Verifying installation...${NC}"
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



echo -n "  ⬡ credential store... "
if [ -n "$HIVE_CREDENTIAL_KEY" ] && [ -d "$HOME/.hive/credentials/credentials" ]; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${YELLOW}--${NC}"
fi

echo -n "  ⬡ frontend... "
if [ -f "$SCRIPT_DIR/core/frontend/dist/index.html" ]; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${YELLOW}--${NC}"
fi

echo -n "  ⬡ browser extension... "
if [ "$CHROME_LAUNCHED" = true ]; then
    echo -e "${GREEN}ok${NC}"
elif [ -d "$EXTENSION_PATH" ] && [ -n "$CHROME_BIN" ]; then
    echo -e "${GREEN}ok${NC}"
elif [ -d "$EXTENSION_PATH" ]; then
    echo -e "${YELLOW}-- (Chrome not found)${NC}"
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
# Step 6: Install hive CLI globally
# ============================================================

echo -e "${YELLOW}⬢${NC} ${BLUE}${BOLD}Step 6: Installing hive CLI...${NC}"
echo ""

# Ensure ~/.local/bin exists and is in PATH
mkdir -p "$HOME/.local/bin"

# Git Bash on Windows may materialize `ln -s` as a plain file copy.
# Use a launcher shim there, but prefer a real symlink on Linux/macOS.
HIVE_SCRIPT="$SCRIPT_DIR/hive"
HIVE_LINK="$HOME/.local/bin/hive"
HIVE_SCRIPT_ESCAPED=$(printf '%q' "$HIVE_SCRIPT")

if [ -L "$HIVE_LINK" ] || [ -e "$HIVE_LINK" ]; then
    rm -f "$HIVE_LINK"
fi

if [ -n "$MSYSTEM" ] || [ -n "$MINGW_PREFIX" ]; then
    cat > "$HIVE_LINK" <<EOF
#!/usr/bin/env bash
set -e
HIVE_SCRIPT=$HIVE_SCRIPT_ESCAPED
exec "\$HIVE_SCRIPT" "\$@"
EOF
    chmod +x "$HIVE_LINK"
else
    ln -s "$HIVE_SCRIPT" "$HIVE_LINK"
fi
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
# Initialize Queen Profiles
# ============================================================

echo -n "  ⬡ queen profiles... "
if uv run python -c "from framework.agents.queen.queen_profiles import ensure_default_queens; ensure_default_queens()" > /dev/null 2>&1; then
    echo -e "${GREEN}ok${NC}"
else
    echo -e "${YELLOW}skipped${NC} ${DIM}(non-fatal)${NC}"
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
    elif [ "$SUBSCRIPTION_MODE" = "minimax_code" ]; then
        echo -e "  ${GREEN}⬢${NC} MiniMax Coding Key → ${DIM}$SELECTED_MODEL${NC}"
        echo -e "  ${DIM}API: api.minimax.io/v1 (OpenAI-compatible)${NC}"
    elif [ "$SELECTED_PROVIDER_ID" = "openrouter" ]; then
        echo -e "  ${GREEN}⬢${NC} OpenRouter API Key → ${DIM}$SELECTED_MODEL${NC}"
        echo -e "  ${DIM}API: openrouter.ai/api/v1 (OpenAI-compatible)${NC}"
    elif [ "$SELECTED_PROVIDER_ID" = "ollama" ]; then
        echo -e "  ${GREEN}⬢${NC} Local (Ollama) → ${DIM}$SELECTED_MODEL${NC}"
        echo -e "  ${DIM}No API key required (runs locally via http://localhost:11434)${NC}"
    else
        echo -e "  ${CYAN}$SELECTED_PROVIDER_ID${NC} → ${DIM}$SELECTED_MODEL${NC}"
    fi
    echo -e "  ${DIM}To use a different model for worker agents, run:${NC}"
    echo -e "     ${CYAN}./scripts/setup_worker_model.sh${NC}"
    echo ""
fi

# Show credential store status
if [ -n "$HIVE_CREDENTIAL_KEY" ]; then
    echo -e "${BOLD}Credential Store:${NC}"
    echo -e "  ${GREEN}⬢${NC} ${DIM}~/.hive/credentials/${NC}  (encrypted)"
    echo ""
fi

# Show tool summary
TOOL_COUNTS=$(uv run python -c "
from fastmcp import FastMCP
from aden_tools.tools import register_all_tools
mv = FastMCP('v')
v = register_all_tools(mv, include_unverified=False)
ma = FastMCP('a')
a = register_all_tools(ma, include_unverified=True)
print(f'{len(v)}|{len(a) - len(v)}')
" 2>/dev/null)
if [ -n "$TOOL_COUNTS" ]; then
    VERIFIED=$(echo "$TOOL_COUNTS" | cut -d'|' -f1)
    UNVERIFIED=$(echo "$TOOL_COUNTS" | cut -d'|' -f2)
    echo -e "${BOLD}Tools:${NC}"
    echo -e "  ${GREEN}⬢${NC} ${VERIFIED} verified    ${DIM}${UNVERIFIED} unverified available${NC}"
    echo -e "  ${DIM}Enable unverified: INCLUDE_UNVERIFIED_TOOLS=true${NC}"
    echo -e "  ${DIM}Learn more: docs/tools.md${NC}"
    echo ""
fi

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

echo -e "${DIM}API keys saved to ${CYAN}$SHELL_RC_FILE${NC}${DIM}. New terminals pick them up automatically.${NC}"
echo -e "${DIM}Launch anytime from this project root with ${CYAN}./hive open${NC}${DIM}. Run ./quickstart.sh again to reconfigure.${NC}"
echo ""

if [ "$FRONTEND_BUILT" = true ]; then
    echo -e "${BOLD}Launching dashboard...${NC}"
    echo ""
    "$SCRIPT_DIR/hive" open
else
    echo -e "${YELLOW}Frontend build was skipped or failed.${NC} Launch manually when ready:"
    echo -e "     ${CYAN}./hive open${NC}"
    echo ""
fi
