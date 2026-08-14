#!/bin/bash
set -euo pipefail

us=$(printf "\037")

echo "Testing ollama_local preset..."
line="PRESET${us}ollama_local${us}ollama${us}${us}4096${us}8192${us}${us}http://localhost:11434"
IFS="$us" read -r kind preset provider model max_tokens max_context env_var api_base <<< "$line"
test "$kind" = "PRESET"
test "$preset" = "ollama_local"
test "$provider" = "ollama"
test "$model" = ""
test "$max_tokens" = "4096"
test "$max_context" = "8192"
test "$env_var" = ""
test "$api_base" = "http://localhost:11434"

echo "Testing ollama_cloud preset..."
line="PRESET${us}ollama_cloud${us}ollama${us}${us}4096${us}8192${us}${us}"
IFS="$us" read -r kind preset provider model max_tokens max_context env_var api_base <<< "$line"
test "$preset" = "ollama_cloud"
test "$env_var" = ""
test "$api_base" = ""

echo "Testing vision fallback..."
line="openrouter${us}model${us}${us}OpenRouter/model"
IFS="$us" read -r vf_provider vf_model vf_env vf_display <<< "$line"
test "$vf_provider" = "openrouter"
test "$vf_model" = "model"
test "$vf_env" = ""
test "$vf_display" = "OpenRouter/model"

echo "All parsing tests passed successfully."
