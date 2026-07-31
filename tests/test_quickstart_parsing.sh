#!/usr/bin/env bash
# test_quickstart_parsing.sh - Regression test for bash 3.2 empty-field collapse bug
# Tests that load_model_catalog_rows and get_preset_field correctly handle empty fields

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source the quickstart script to get access to its functions
source "$PROJECT_ROOT/quickstart.sh"

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Test helper functions
test_start() {
    echo -e "${YELLOW}TEST: $1${NC}"
    ((TESTS_RUN++))
}

test_pass() {
    echo -e "${GREEN}  ✓ PASS${NC}"
    ((TESTS_PASSED++))
}

test_fail() {
    echo -e "${RED}  ✗ FAIL: $1${NC}"
    ((TESTS_FAILED++))
}

assert_equals() {
    local expected="$1"
    local actual="$2"
    local message="$3"
    
    if [[ "$expected" == "$actual" ]]; then
        test_pass
    else
        test_fail "$message (expected: '$expected', got: '$actual')"
    fi
}

# Test 1: Load catalog rows
test_start "load_model_catalog_rows loads preset data"
if load_model_catalog_rows; then
    if [[ ${#PRESET_ROWS[@]} -gt 0 ]]; then
        test_pass
    else
        test_fail "No rows loaded"
    fi
else
    test_fail "Function returned error"
fi

# Test 2: Verify ollama_local preset exists
test_start "ollama_local preset exists in catalog"
found=false
for row in "${PRESET_ROWS[@]}"; do
    if [[ "$row" == ollama_local* ]]; then
        found=true
        break
    fi
done

if [[ "$found" == "true" ]]; then
    test_pass
else
    test_fail "ollama_local preset not found"
fi

# Test 3: Extract ollama_local fields (the critical test for empty field handling)
test_start "get_preset_field correctly extracts ollama_local provider"
provider=$(get_preset_field "ollama_local" 1)
assert_equals "ollama" "$provider" "Provider field mismatch"

test_start "get_preset_field correctly handles empty model field"
model=$(get_preset_field "ollama_local" 2)
assert_equals "" "$model" "Model field should be empty"

test_start "get_preset_field correctly handles empty api_key_env_var field"
api_key_env_var=$(get_preset_field "ollama_local" 3)
assert_equals "" "$api_key_env_var" "API key env var field should be empty"

test_start "get_preset_field correctly extracts ollama_local base_url"
base_url=$(get_preset_field "ollama_local" 4)
assert_equals "http://localhost:11434" "$base_url" "Base URL field mismatch"

test_start "get_preset_field correctly extracts ollama_local max_tokens"
max_tokens=$(get_preset_field "ollama_local" 5)
assert_equals "4096" "$max_tokens" "Max tokens field mismatch"

# Test 4: Verify max_tokens is numeric (regression test for ValueError)
test_start "ollama_local max_tokens is a valid integer"
if [[ "$max_tokens" =~ ^[0-9]+$ ]]; then
    test_pass
else
    test_fail "max_tokens '$max_tokens' is not a valid integer"
fi

# Test 5: Test ollama_cloud preset (also has empty fields)
test_start "get_preset_field correctly extracts ollama_cloud provider"
provider=$(get_preset_field "ollama_cloud" 1)
assert_equals "ollama" "$provider" "Provider field mismatch"

test_start "get_preset_field correctly handles empty model field for ollama_cloud"
model=$(get_preset_field "ollama_cloud" 2)
assert_equals "" "$model" "Model field should be empty"

test_start "get_preset_field correctly extracts ollama_cloud api_key_env_var"
api_key_env_var=$(get_preset_field "ollama_cloud" 3)
assert_equals "OLLAMA_API_KEY" "$api_key_env_var" "API key env var field mismatch"

# Test 6: Test a preset with all fields populated (anthropic)
test_start "get_preset_field correctly extracts anthropic fields"
provider=$(get_preset_field "anthropic" 1)
assert_equals "anthropic" "$provider" "Anthropic provider mismatch"

model=$(get_preset_field "anthropic" 2)
assert_equals "claude-3-5-sonnet-20241022" "$model" "Anthropic model mismatch"

api_key_env_var=$(get_preset_field "anthropic" 3)
assert_equals "ANTHROPIC_API_KEY" "$api_key_env_var" "Anthropic API key env var mismatch"

# Test 7: Test apply_preset with ollama_local (end-to-end test)
test_start "apply_preset successfully configures ollama_local"
if apply_preset "ollama_local" >/dev/null 2>&1; then
    # Verify the environment variables are set correctly
    if [[ "$SELECTED_PROVIDER" == "ollama" ]] && \
       [[ "$SELECTED_MODEL" == "" ]] && \
       [[ "$SELECTED_API_KEY_ENV_VAR" == "" ]] && \
       [[ "$SELECTED_BASE_URL" == "http://localhost:11434" ]] && \
       [[ "$SELECTED_MAX_TOKENS" == "4096" ]]; then
        test_pass
    else
        test_fail "Environment variables not set correctly (provider=$SELECTED_PROVIDER, model=$SELECTED_MODEL, api_key=$SELECTED_API_KEY_ENV_VAR, base_url=$SELECTED_BASE_URL, max_tokens=$SELECTED_MAX_TOKENS)"
    fi
else
    test_fail "apply_preset failed"
fi

# Test 8: Verify max_tokens validation catches non-numeric values
test_start "apply_preset rejects non-numeric max_tokens"
# Temporarily corrupt a preset row to test validation
original_rows=("${PRESET_ROWS[@]}")
PRESET_ROWS=("test_invalid"$'\x1F'"provider"$'\x1F'"model"$'\x1F'"key"$'\x1F'"url"$'\x1F'"not_a_number"$'\x1F'"desc")

if apply_preset "test_invalid" >/dev/null 2>&1; then
    test_fail "Should have rejected non-numeric max_tokens"
else
    test_pass
fi

# Restore original rows
PRESET_ROWS=("${original_rows[@]}")

# Summary
echo -e "\n${YELLOW}=== Test Summary ===${NC}"
echo -e "Tests run: $TESTS_RUN"
echo -e "${GREEN}Passed: $TESTS_PASSED${NC}"
if [[ $TESTS_FAILED -gt 0 ]]; then
    echo -e "${RED}Failed: $TESTS_FAILED${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
fi
