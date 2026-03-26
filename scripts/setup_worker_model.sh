#!/bin/bash
#
# setup_worker_model.sh - Configure a separate LLM model for worker agents
#
# Worker agents can use a different (e.g. cheaper/faster) model than the
# queen agent.  This script writes a "worker_llm" section to
# ~/.hive/configuration.json.  If no worker model is configured, workers
# fall back to the default (queen) model.
#
# The provider selection flow is identical to quickstart.sh.
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

# Hive LLM endpoint
HIVE_LLM_ENDPOINT="https://api.adenhq.com"

# Get the directory where this script is located, then the project root
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
HIVE_CONFIG_DIR="$HOME/.hive"
HIVE_CONFIG_FILE="$HIVE_CONFIG_DIR/configuration.json"

# ── Detect Python ─────────────────────────────────────────────────────
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
    PYTHON_CMD="python3"
    if ! command -v python3 &> /dev/null; then
        PYTHON_CMD="python"
    fi
fi

# ── Provider / model definitions (identical to quickstart) ────────────

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

# ── Detect user's shell rc file ──────────────────────────────────────

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
            echo "$HOME/.profile"
            ;;
    esac
}

SHELL_RC_FILE=$(detect_shell_rc)

# ── Normalize OpenRouter model IDs ───────────────────────────────────

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

# ── Model selection prompt (identical to quickstart) ─────────────────

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
                    model_hc_result="$(cd "$PROJECT_DIR" && uv run python "$PROJECT_DIR/scripts/check_llm_key.py" "openrouter" "$openrouter_key" "$model_hc_base" "$normalized_model" 2>/dev/null)" || true
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
        SELECTED_MAX_CONTEXT_TOKENS=120000
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

# ── Save worker_llm section to configuration.json ────────────────────
# Args: provider_id env_var model max_tokens max_context_tokens [use_claude_code_sub] [api_base] [use_codex_sub] [use_antigravity_sub]

save_worker_configuration() {
    local provider_id="$1"
    local env_var="$2"
    local model="$3"
    local max_tokens="$4"
    local max_context_tokens="$5"
    local use_claude_code_sub="${6:-}"
    local api_base="${7:-}"
    local use_codex_sub="${8:-}"
    local use_antigravity_sub="${9:-}"

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
        "$use_claude_code_sub" \
        "$api_base" \
        "$use_codex_sub" \
        "$use_antigravity_sub" 2>/dev/null <<'PY'
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
) = sys.argv[1:10]

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
    "api_key_env_var": env_var,
}

if use_claude_code_sub == "true":
    config["worker_llm"]["use_claude_code_subscription"] = True
    config["worker_llm"].pop("api_key_env_var", None)
else:
    config["worker_llm"].pop("use_claude_code_subscription", None)

if use_codex_sub == "true":
    config["worker_llm"]["use_codex_subscription"] = True
    config["worker_llm"].pop("api_key_env_var", None)
else:
    config["worker_llm"].pop("use_codex_subscription", None)

if use_antigravity_sub == "true":
    config["worker_llm"]["use_antigravity_subscription"] = True
    config["worker_llm"].pop("api_key_env_var", None)
    import os as _os
    _secret = _os.environ.get("ANTIGRAVITY_CLIENT_SECRET") or ""
    if _secret:
        config["worker_llm"]["antigravity_client_secret"] = _secret
    _client_id = _os.environ.get("ANTIGRAVITY_CLIENT_ID") or ""
    if _client_id:
        config["worker_llm"]["antigravity_client_id"] = _client_id
else:
    config["worker_llm"].pop("use_antigravity_subscription", None)
    config["worker_llm"].pop("antigravity_client_secret", None)
    config["worker_llm"].pop("antigravity_client_id", None)

if api_base:
    config["worker_llm"]["api_base"] = api_base
else:
    config["worker_llm"].pop("api_base", None)

if not env_var:
    config["worker_llm"].pop("api_key_env_var", None)

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

# Source shell rc file to pick up existing env vars (temporarily disable set -e)
set +e
if [ -f "$SHELL_RC_FILE" ]; then
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

# ── Read previous worker configuration (if any) ──────────────────────
PREV_PROVIDER=""
PREV_MODEL=""
PREV_ENV_VAR=""
PREV_SUB_MODE=""
if [ -f "$HIVE_CONFIG_FILE" ]; then
    eval "$(cd "$PROJECT_DIR" && uv run python - 2>/dev/null <<'PY'
import json
from pathlib import Path

cfg_path = Path.home() / ".hive" / "configuration.json"
try:
    with open(cfg_path, encoding="utf-8-sig") as f:
        c = json.load(f)
    llm = c.get("worker_llm", {})
    print(f"PREV_PROVIDER={llm.get('provider', '')}")
    print(f"PREV_MODEL={llm.get('model', '')}")
    print(f"PREV_ENV_VAR={llm.get('api_key_env_var', '')}")
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
            # API key provider — check if the env var is set
            if [ -n "$PREV_ENV_VAR" ] && [ -n "${!PREV_ENV_VAR}" ]; then
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
                minimax)   DEFAULT_CHOICE=4 ;;
                kimi)      DEFAULT_CHOICE=5 ;;
                hive)      DEFAULT_CHOICE=6 ;;
            esac
        fi
    fi
fi

# ── Show unified provider selection menu ─────────────────────
echo -e "${BOLD}Select your worker LLM provider:${NC}"
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
if [ "$HIVE_CRED_DETECTED" = true ]; then
    echo -e "  ${CYAN}6)${NC} Hive LLM                   ${DIM}(use your Hive API key)${NC}  ${GREEN}(credential detected)${NC}"
else
    echo -e "  ${CYAN}6)${NC} Hive LLM                   ${DIM}(use your Hive API key)${NC}"
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

SKIP_CHOICE=$((8 + ${#PROVIDER_MENU_ENVS[@]}))
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
            echo -e "  then run this script again."
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
            if cd "$PROJECT_DIR" && uv run python "$PROJECT_DIR/core/codex_oauth.py"; then
                CODEX_CRED_DETECTED=true
            else
                echo ""
                echo -e "${RED}  OAuth login failed or was cancelled.${NC}"
                echo ""
                echo -e "  To authenticate manually, visit:"
                echo -e "  ${CYAN}https://auth.openai.com/authorize?client_id=app_EMoamEEZ73f0CkXaXp7hrann&response_type=code&redirect_uri=http://localhost:1455/auth/callback&scope=openid%20profile%20email%20offline_access${NC}"
                echo ""
                echo -e "  Or run ${CYAN}codex${NC} to authenticate, then run this script again."
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
            if uv run python "$PROJECT_DIR/core/antigravity_auth.py" auth account add; then
                # Re-detect credentials
                if [ -f "$HOME/.hive/antigravity-accounts.json" ]; then
                    ANTIGRAVITY_CRED_DETECTED=true
                fi
            fi

            if [ "$ANTIGRAVITY_CRED_DETECTED" = false ]; then
                echo ""
                echo -e "${RED}  Authentication failed or was cancelled.${NC}"
                echo ""
                exit 1
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
    "$SKIP_CHOICE")
        echo ""
        echo -e "${YELLOW}Skipped.${NC} Worker model not configured."
        echo -e "Run this script again when ready."
        echo ""
        exit 0
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
                HC_RESULT=$(cd "$PROJECT_DIR" && uv run python "$PROJECT_DIR/scripts/check_llm_key.py" "$SELECTED_PROVIDER_ID" "$API_KEY" "$SELECTED_API_BASE" 2>/dev/null) || true
            else
                HC_RESULT=$(cd "$PROJECT_DIR" && uv run python "$PROJECT_DIR/scripts/check_llm_key.py" "$SELECTED_PROVIDER_ID" "$API_KEY" 2>/dev/null) || true
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
            HC_RESULT=$(cd "$PROJECT_DIR" && uv run python "$PROJECT_DIR/scripts/check_llm_key.py" "zai" "$API_KEY" "https://api.z.ai/api/coding/paas/v4" 2>/dev/null) || true
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

# Save worker configuration if a provider was selected
if [ -n "$SELECTED_PROVIDER_ID" ]; then
    echo ""
    echo -n "  Saving worker model configuration... "
    SAVE_OK=true
    if [ "$SUBSCRIPTION_MODE" = "claude_code" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "true" "" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "codex" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "" "true" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "antigravity" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "" "" "true" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "zai_code" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "https://api.z.ai/api/coding/paas/v4" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "minimax_code" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "kimi_code" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SUBSCRIPTION_MODE" = "hive_llm" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    elif [ "$SELECTED_PROVIDER_ID" = "openrouter" ]; then
        save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" "" "$SELECTED_API_BASE" > /dev/null || SAVE_OK=false
    else
        save_worker_configuration "$SELECTED_PROVIDER_ID" "$SELECTED_ENV_VAR" "$SELECTED_MODEL" "$SELECTED_MAX_TOKENS" "$SELECTED_MAX_CONTEXT_TOKENS" > /dev/null || SAVE_OK=false
    fi
    if [ "$SAVE_OK" = false ]; then
        echo -e "${RED}failed${NC}"
        echo -e "${YELLOW}  Could not write ~/.hive/configuration.json. Please rerun this script.${NC}"
        exit 1
    fi
    echo -e "${GREEN}done${NC}"
    echo -e "  ${DIM}~/.hive/configuration.json (worker_llm section)${NC}"
    echo ""
    echo -e "${GREEN}⬢${NC} Worker model configured successfully."
    echo -e "  ${DIM}Worker agents will now use: ${SELECTED_PROVIDER_ID}/${SELECTED_MODEL}${NC}"
    echo -e "  ${DIM}Run this script again to change, or remove the worker_llm section${NC}"
    echo -e "  ${DIM}from ~/.hive/configuration.json to revert to the default.${NC}"
    echo ""
fi
