#!/usr/bin/env bash
# quickstart.sh - Interactive setup script for the project

set -euo pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load model catalog rows from Python helper
# Fixed: Use a delimiter that won't collapse empty fields on bash 3.2
load_model_catalog_rows() {
    local python_script="${SCRIPT_DIR}/core/framework/llm/model_catalog.py"
    
    if [[ ! -f "$python_script" ]]; then
        echo -e "${RED}Error: model_catalog.py not found at $python_script${NC}" >&2
        return 1
    fi
    
    # Use a unique delimiter (ASCII 0x1F Unit Separator) instead of tab
    # This prevents bash 3.2 from collapsing empty fields
    local delimiter=$'\x1F'
    
    # Read TSV output from Python, convert tabs to our delimiter
    PRESET_ROWS=()
    while IFS= read -r line; do
        # Convert tabs to our delimiter character
        local converted_line="${line//$'\t'/$delimiter}"
        PRESET_ROWS+=("$converted_line")
    done < <(python3 "$python_script" list-presets 2>/dev/null || echo "")
    
    if [[ ${#PRESET_ROWS[@]} -eq 0 ]]; then
        echo -e "${RED}Error: No presets loaded from model catalog${NC}" >&2
        return 1
    fi
    
    return 0
}

# Get a specific field from a preset row
# Fixed: Use the same delimiter to avoid field collapse on bash 3.2
get_preset_field() {
    local preset_name="$1"
    local field_index="$2"  # 0=name, 1=provider, 2=model, 3=api_key_env_var, 4=base_url, 5=max_tokens, 6=description
    
    local delimiter=$'\x1F'
    
    for row in "${PRESET_ROWS[@]}"; do
        # Split on our delimiter instead of tab
        local -a fields
        IFS="$delimiter" read -ra fields <<< "$row"
        
        if [[ "${fields[0]}" == "$preset_name" ]]; then
            # Return the requested field, or empty string if out of bounds
            if [[ $field_index -lt ${#fields[@]} ]]; then
                echo "${fields[$field_index]}"
            else
                echo ""
            fi
            return 0
        fi
    done
    
    echo -e "${RED}Error: Preset '$preset_name' not found${NC}" >&2
    return 1
}

# Apply a preset configuration
apply_preset() {
    local preset_name="$1"
    
    echo -e "${GREEN}Applying preset: $preset_name${NC}"
    
    local provider model api_key_env_var base_url max_tokens description
    
    provider=$(get_preset_field "$preset_name" 1) || return 1
    model=$(get_preset_field "$preset_name" 2) || return 1
    api_key_env_var=$(get_preset_field "$preset_name" 3) || return 1
    base_url=$(get_preset_field "$preset_name" 4) || return 1
    max_tokens=$(get_preset_field "$preset_name" 5) || return 1
    description=$(get_preset_field "$preset_name" 6) || return 1
    
    # Write configuration
    export SELECTED_PROVIDER="$provider"
    export SELECTED_MODEL="$model"
    export SELECTED_API_KEY_ENV_VAR="$api_key_env_var"
    export SELECTED_BASE_URL="$base_url"
    export SELECTED_MAX_TOKENS="$max_tokens"
    
    # Validate max_tokens is numeric
    if [[ -n "$max_tokens" ]] && ! [[ "$max_tokens" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}Error: Invalid max_tokens value: '$max_tokens' (expected integer)${NC}" >&2
        return 1
    fi
    
    echo -e "${GREEN}Configuration applied successfully${NC}"
    echo -e "  Provider: $provider"
    echo -e "  Model: ${model:-<default>}"
    echo -e "  Base URL: ${base_url:-<default>}"
    echo -e "  Max Tokens: $max_tokens"
    
    return 0
}

# Main interactive menu
main() {
    echo -e "${GREEN}=== Quickstart Setup ===${NC}\n"
    
    # Load catalog
    if ! load_model_catalog_rows; then
        echo -e "${RED}Failed to load model catalog${NC}"
        exit 1
    fi
    
    echo -e "Available presets:\n"
    
    local -a preset_names
    for row in "${PRESET_ROWS[@]}"; do
        local name description
        name=$(get_preset_field "$(echo "$row" | cut -d$'\x1F' -f1)" 0)
        description=$(get_preset_field "$name" 6)
        preset_names+=("$name")
        echo -e "  ${YELLOW}$name${NC}: $description"
    done
    
    echo -e "\nSelect a preset (or press Ctrl+C to exit):"
    select preset in "${preset_names[@]}"; do
        if [[ -n "$preset" ]]; then
            if apply_preset "$preset"; then
                echo -e "\n${GREEN}Setup complete!${NC}"
                break
            else
                echo -e "\n${RED}Setup failed${NC}"
                exit 1
            fi
        else
            echo -e "${RED}Invalid selection${NC}"
        fi
    done
}

# Run main if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
