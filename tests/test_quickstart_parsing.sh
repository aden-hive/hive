#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

source "${SCRIPT_DIR}/quickstart.sh" 2>/dev/null || true

assert_eq() {
    local name="$1" actual="$2" expected="$3"
    if [ "$actual" = "$expected" ]; then
        echo "PASS: $name"
    else
        echo "FAIL: $name (expected=[$expected], actual=[$actual])"
        exit 1
    fi
}

load_model_catalog_rows

assert_eq "ollama_local provider"            "$(get_preset_field ollama_local provider)" "ollama"
assert_eq "ollama_local empty model"          "$(get_preset_field ollama_local model)" ""
assert_eq "ollama_local max_tokens"           "$(get_preset_field ollama_local max_tokens)" "8192"
assert_eq "ollama_local max_context_tokens"   "$(get_preset_field ollama_local max_context_tokens)" "131072"
assert_eq "ollama_local empty env_var"        "$(get_preset_field ollama_local api_key_env_var)" ""
assert_eq "ollama_local api_base"             "$(get_preset_field ollama_local api_base)" "http://localhost:11434"

assert_eq "ollama_cloud provider"             "$(get_preset_field ollama_cloud provider)" "ollama"
assert_eq "ollama_cloud empty model"          "$(get_preset_field ollama_cloud model)" ""
assert_eq "ollama_cloud api_key_env_var"      "$(get_preset_field ollama_cloud api_key_env_var)" "OLLAMA_API_KEY"

assert_eq "zai_code provider"                 "$(get_preset_field zai_code provider)" "openai"
assert_eq "zai_code model"                    "$(get_preset_field zai_code model)" "glm-5.1"
assert_eq "zai_code max_tokens"               "$(get_preset_field zai_code max_tokens)" "32768"

echo ""
echo "All tests passed on $(bash --version | head -1)"
