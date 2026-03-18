#!/bin/bash
#
# setup_worker_model.sh - Configure a separate LLM model for worker agents
#
# Worker agents can use a different (e.g. cheaper/faster) model than the
# queen agent.  This script writes a "worker_llm" section to
# ~/.hive/configuration.json.  If no worker model is configured, workers
# fall back to the default (queen) model.
#

set -e

# Detect Bash version for compatibility
BASH_MAJOR_VERSION="${BASH_VERSINFO[0]}"
USE_ASSOC_ARRAYS=false
if [ "$BASH_MAJOR_VERSION" -ge 4 ]; then
    USE_ASSOC_ARRAYS=true
fi

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Get the directory where this script is located, then the project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
HIVE_CONFIG_FILE="$HOME/.hive/configuration.json"

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

# ── Provider / model definitions (same as quickstart) ────────────────

if [ "$USE_ASSOC_ARRAYS" = true ]; then
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
        ["anthropic:0"]="Haiku 4.5 - Fast + cheap (recommended for workers)"
        ["anthropic:1"]="Sonnet 4 - Fast + capable"
        ["anthropic:2"]="Sonnet 4.5 - Best balance"
        ["anthropic:3"]="Opus 4.6 - Most capable"
        ["openai:0"]="GPT-5 Mini - Fast + cheap (recommended for workers)"
        ["openai:1"]="GPT-5.2 - Most capable"
        ["gemini:0"]="Gemini 3 Flash - Fast (recommended for workers)"
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

    declare -A MODEL_CHOICES_MAXCONTEXTTOKENS=(
        ["anthropic:0"]=180000
        ["anthropic:1"]=180000
        ["anthropic:2"]=180000
        ["anthropic:3"]=180000
        ["openai:0"]=120000
        ["openai:1"]=120000
        ["gemini:0"]=900000
        ["gemini:1"]=900000
        ["groq:0"]=120000
        ["groq:1"]=120000
        ["cerebras:0"]=120000
        ["cerebras:1"]=120000
    )

    declare -A MODEL_CHOICES_COUNT=(
        ["anthropic"]=4
        ["openai"]=2
        ["gemini"]=2
        ["groq"]=2
        ["cerebras"]=2
    )

    get_provider_name()  { echo "${PROVIDER_NAMES[$1]}"; }
    get_provider_id()    { echo "${PROVIDER_IDS[$1]}"; }
    get_default_model()  { echo "${DEFAULT_MODELS[$1]}"; }
    get_model_choice_count() { echo "${MODEL_CHOICES_COUNT[$1]:-0}"; }
    get_model_choice_id()    { echo "${MODEL_CHOICES_ID[$1:$2]}"; }
    get_model_choice_label() { echo "${MODEL_CHOICES_LABEL[$1:$2]}"; }
    get_model_choice_maxtokens()       { echo "${MODEL_CHOICES_MAXTOKENS[$1:$2]}"; }
    get_model_choice_maxcontexttokens() { echo "${MODEL_CHOICES_MAXCONTEXTTOKENS[$1:$2]}"; }
else
    # Bash 3.2 fallback
    PROVIDER_ENV_VARS=(ANTHROPIC_API_KEY OPENAI_API_KEY MINIMAX_API_KEY GEMINI_API_KEY GOOGLE_API_KEY GROQ_API_KEY CEREBRAS_API_KEY OPENROUTER_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY DEEPSEEK_API_KEY)
    PROVIDER_DISPLAY_NAMES=("Anthropic (Claude)" "OpenAI (GPT)" "MiniMax" "Google Gemini" "Google AI" "Groq" "Cerebras" "OpenRouter" "Mistral" "Together AI" "DeepSeek")
    PROVIDER_ID_LIST=(anthropic openai minimax gemini google groq cerebras openrouter mistral together deepseek)

    MODEL_PROVIDER_IDS=(anthropic openai minimax gemini groq cerebras mistral together_ai deepseek)
    MODEL_DEFAULTS=("claude-haiku-4-5-20251001" "gpt-5-mini" "MiniMax-M2.5" "gemini-3-flash-preview" "moonshotai/kimi-k2-instruct-0905" "zai-glm-4.7" "mistral-large-latest" "meta-llama/Llama-3.3-70B-Instruct-Turbo" "deepseek-chat")

    get_provider_name() {
        local env_var="$1"; local i=0
        while [ $i -lt ${#PROVIDER_ENV_VARS[@]} ]; do
            if [ "${PROVIDER_ENV_VARS[$i]}" = "$env_var" ]; then echo "${PROVIDER_DISPLAY_NAMES[$i]}"; return; fi
            i=$((i + 1))
        done
    }
    get_provider_id() {
        local env_var="$1"; local i=0
        while [ $i -lt ${#PROVIDER_ENV_VARS[@]} ]; do
            if [ "${PROVIDER_ENV_VARS[$i]}" = "$env_var" ]; then echo "${PROVIDER_ID_LIST[$i]}"; return; fi
            i=$((i + 1))
        done
    }
    get_default_model() {
        local provider_id="$1"; local i=0
        while [ $i -lt ${#MODEL_PROVIDER_IDS[@]} ]; do
            if [ "${MODEL_PROVIDER_IDS[$i]}" = "$provider_id" ]; then echo "${MODEL_DEFAULTS[$i]}"; return; fi
            i=$((i + 1))
        done
    }

    MC_PROVIDERS=(anthropic anthropic anthropic anthropic openai openai gemini gemini groq groq cerebras cerebras)
    MC_IDS=("claude-haiku-4-5-20251001" "claude-sonnet-4-20250514" "claude-sonnet-4-5-20250929" "claude-opus-4-6" "gpt-5-mini" "gpt-5.2" "gemini-3-flash-preview" "gemini-3.1-pro-preview" "moonshotai/kimi-k2-instruct-0905" "openai/gpt-oss-120b" "zai-glm-4.7" "qwen3-235b-a22b-instruct-2507")
    MC_LABELS=("Haiku 4.5 - Fast + cheap (recommended for workers)" "Sonnet 4 - Fast + capable" "Sonnet 4.5 - Best balance" "Opus 4.6 - Most capable" "GPT-5 Mini - Fast + cheap (recommended for workers)" "GPT-5.2 - Most capable" "Gemini 3 Flash - Fast (recommended for workers)" "Gemini 3.1 Pro - Best quality" "Kimi K2 - Best quality (recommended)" "GPT-OSS 120B - Fast reasoning" "ZAI-GLM 4.7 - Best quality (recommended)" "Qwen3 235B - Frontier reasoning")
    MC_MAXTOKENS=(8192 8192 16384 32768 16384 16384 8192 8192 8192 8192 8192 8192)
    MC_MAXCONTEXTTOKENS=(180000 180000 180000 180000 120000 120000 900000 900000 120000 120000 120000 120000)

    get_model_choice_count() {
        local p="$1"; local cnt=0; local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$p" ]; then cnt=$((cnt + 1)); fi
            i=$((i + 1))
        done
        echo "$cnt"
    }
    _mc_nth() {
        local p="$1"; local n="$2"; local cnt=0; local i=0
        while [ $i -lt ${#MC_PROVIDERS[@]} ]; do
            if [ "${MC_PROVIDERS[$i]}" = "$p" ]; then
                if [ "$cnt" -eq "$n" ]; then echo "$i"; return; fi
                cnt=$((cnt + 1))
            fi
            i=$((i + 1))
        done
    }
    get_model_choice_id()    { local idx=$(_mc_nth "$1" "$2"); echo "${MC_IDS[$idx]}"; }
    get_model_choice_label() { local idx=$(_mc_nth "$1" "$2"); echo "${MC_LABELS[$idx]}"; }
    get_model_choice_maxtokens()       { local idx=$(_mc_nth "$1" "$2"); echo "${MC_MAXTOKENS[$idx]}"; }
    get_model_choice_maxcontexttokens() { local idx=$(_mc_nth "$1" "$2"); echo "${MC_MAXCONTEXTTOKENS[$idx]}"; }
fi

# ── Model selection prompt ───────────────────────────────────────────

select_model() {
    local provider_id="$1"
    local count
    count=$(get_model_choice_count "$provider_id")

    if [ "$count" -eq 0 ]; then
        SELECTED_MODEL="$(get_default_model "$provider_id")"
        SELECTED_MAX_TOKENS=8192
        SELECTED_MAX_CONTEXT_TOKENS=120000
        echo ""
        echo -e "${GREEN}⬢${NC} Worker model: ${DIM}$SELECTED_MODEL${NC}"
        return
    fi

    echo ""
    echo -e "${BOLD}Select worker model:${NC}"
    local i=0
    while [ "$i" -lt "$count" ]; do
        echo -e "  ${CYAN}$((i+1)))${NC} $(get_model_choice_label "$provider_id" "$i")"
        i=$((i + 1))
    done
    echo ""

    while true; do
        local default_idx=1
        read -r -p "Enter choice (1-$count) [$default_idx]: " choice || true
        choice="${choice:-$default_idx}"
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "$count" ]; then
            local idx=$((choice - 1))
            SELECTED_MODEL="$(get_model_choice_id "$provider_id" "$idx")"
            SELECTED_MAX_TOKENS="$(get_model_choice_maxtokens "$provider_id" "$idx")"
            SELECTED_MAX_CONTEXT_TOKENS="$(get_model_choice_maxcontexttokens "$provider_id" "$idx")"
            echo ""
            echo -e "${GREEN}⬢${NC} Worker model: ${DIM}$SELECTED_MODEL${NC}"
            return
        fi
        echo -e "${RED}Invalid choice. Please enter 1-$count${NC}"
    done
}

# ── Save worker_llm section to configuration.json ────────────────────

save_worker_configuration() {
    local provider_id="$1"
    local env_var="$2"
    local model="$3"
    local max_tokens="$4"
    local max_context_tokens="$5"
    local api_base="${6:-}"

    if [ -z "$model" ]; then
        model="$(get_default_model "$provider_id")"
    fi
    if [ -z "$max_tokens" ]; then max_tokens=8192; fi
    if [ -z "$max_context_tokens" ]; then max_context_tokens=120000; fi

    cd "$PROJECT_DIR"
    uv run python - \
        "$provider_id" \
        "$env_var" \
        "$model" \
        "$max_tokens" \
        "$max_context_tokens" \
        "$api_base" 2>/dev/null <<'PY'
import json
import sys
from pathlib import Path

(
    provider_id,
    env_var,
    model,
    max_tokens,
    max_context_tokens,
    api_base,
) = sys.argv[1:7]

cfg_path = Path.home() / ".hive" / "configuration.json"
cfg_path.parent.mkdir(parents=True, exist_ok=True)

try:
    with open(cfg_path, encoding="utf-8-sig") as f:
        config = json.load(f)
except (OSError, json.JSONDecodeError):
    config = {}

config["worker_llm"] = {
    "provider": provider_id,
    "model": model,
    "max_tokens": int(max_tokens),
    "max_context_tokens": int(max_context_tokens),
}
if env_var:
    config["worker_llm"]["api_key_env_var"] = env_var
if api_base:
    config["worker_llm"]["api_base"] = api_base

tmp_path = cfg_path.with_name(cfg_path.name + ".tmp")
with open(tmp_path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2)
tmp_path.replace(cfg_path)
print(json.dumps(config.get("worker_llm", {}), indent=2))
PY
}

# ── Main ─────────────────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC} ${BOLD}Worker Model Setup${NC} ${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}${DIM}⬡${NC}${YELLOW}⬢${NC}"
echo ""
echo -e "${DIM}Configure a separate LLM model for worker agents.${NC}"
echo -e "${DIM}Worker agents will use this model instead of the default queen model.${NC}"
echo ""

# Show current configuration
if [ -f "$HIVE_CONFIG_FILE" ]; then
    CURRENT_QUEEN=$(cd "$PROJECT_DIR" && uv run python -c "
from framework.config import get_preferred_model, get_preferred_worker_model
print(f'Queen:  {get_preferred_model()}')
wm = get_preferred_worker_model()
print(f'Worker: {wm if wm else \"(same as queen)\"}')
" 2>/dev/null) || true
    if [ -n "$CURRENT_QUEEN" ]; then
        echo -e "${BOLD}Current configuration:${NC}"
        echo -e "  ${DIM}$CURRENT_QUEEN${NC}" | head -1
        echo -e "  ${DIM}$(echo "$CURRENT_QUEEN" | tail -1)${NC}"
        echo ""
    fi
fi

# Source shell rc to pick up env vars
SHELL_RC_FILE="$HOME/.bashrc"
if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ]; then
    SHELL_RC_FILE="$HOME/.zshrc"
fi
set +e
if [ -f "$SHELL_RC_FILE" ]; then
    eval "$(grep -E '^export [A-Z_]+=' "$SHELL_RC_FILE" 2>/dev/null)"
fi
set -e

# Detect available providers
AVAIL_PROVIDERS=()
AVAIL_ENV_VARS=()

ENV_VARS_TO_CHECK=(ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GOOGLE_API_KEY GROQ_API_KEY CEREBRAS_API_KEY OPENROUTER_API_KEY MISTRAL_API_KEY TOGETHER_API_KEY DEEPSEEK_API_KEY)

for ev in "${ENV_VARS_TO_CHECK[@]}"; do
    if [ -n "${!ev:-}" ]; then
        AVAIL_PROVIDERS+=("$(get_provider_name "$ev")")
        AVAIL_ENV_VARS+=("$ev")
    fi
done

if [ ${#AVAIL_PROVIDERS[@]} -eq 0 ]; then
    echo -e "${RED}No API keys found.${NC}"
    echo -e "Run ${CYAN}./quickstart.sh${NC} first to set up your LLM provider."
    exit 1
fi

# Pick provider
SELECTED_PROVIDER_ID=""
SELECTED_ENV_VAR=""
SELECTED_MODEL=""
SELECTED_MAX_TOKENS=8192
SELECTED_MAX_CONTEXT_TOKENS=120000
SELECTED_API_BASE=""

if [ ${#AVAIL_PROVIDERS[@]} -eq 1 ]; then
    SELECTED_ENV_VAR="${AVAIL_ENV_VARS[0]}"
    SELECTED_PROVIDER_ID="$(get_provider_id "$SELECTED_ENV_VAR")"
    echo -e "${GREEN}⬢${NC} Provider: $(get_provider_name "$SELECTED_ENV_VAR")"
else
    echo -e "${BOLD}Select provider for worker agents:${NC}"
    echo ""
    local_i=1
    for prov in "${AVAIL_PROVIDERS[@]}"; do
        echo -e "  ${CYAN}${local_i})${NC} $prov"
        local_i=$((local_i + 1))
    done
    echo ""
    while true; do
        read -r -p "Enter choice (1-${#AVAIL_PROVIDERS[@]}): " choice || true
        if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#AVAIL_PROVIDERS[@]}" ]; then
            idx=$((choice - 1))
            SELECTED_ENV_VAR="${AVAIL_ENV_VARS[$idx]}"
            SELECTED_PROVIDER_ID="$(get_provider_id "$SELECTED_ENV_VAR")"
            echo ""
            echo -e "${GREEN}⬢${NC} Provider: ${AVAIL_PROVIDERS[$idx]}"
            break
        fi
        echo -e "${RED}Invalid choice.${NC}"
    done
fi

# OpenRouter: custom api_base
if [ "$SELECTED_PROVIDER_ID" = "openrouter" ]; then
    SELECTED_API_BASE="https://openrouter.ai/api/v1"
fi

# Select model
select_model "$SELECTED_PROVIDER_ID"

# Option to clear worker model
echo ""
if prompt_yes_no "Save this worker model configuration?"; then
    echo ""
    echo -n "  Saving worker model configuration... "
    if save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "$SELECTED_API_BASE" > /dev/null; then
        echo -e "${GREEN}done${NC}"
        echo -e "  ${DIM}~/.hive/configuration.json (worker_llm section)${NC}"
    else
        echo -e "${RED}failed${NC}"
        exit 1
    fi
else
    echo ""
    echo "Cancelled. Worker agents will continue using the default model."
    exit 0
fi

echo ""
echo -e "${GREEN}⬢${NC} Worker model configured successfully."
echo -e "  ${DIM}Worker agents will now use: ${SELECTED_PROVIDER_ID}/${SELECTED_MODEL}${NC}"
echo -e "  ${DIM}Run this script again to change, or remove the worker_llm section${NC}"
echo -e "  ${DIM}from ~/.hive/configuration.json to revert to the default.${NC}"
echo ""
