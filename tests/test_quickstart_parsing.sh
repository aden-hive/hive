#!/bin/bash
set -euo pipefail

# Extract functions and vision fallback script using python to handle CRLF safely
uv run python -c '
import sys, re
content = open("quickstart.sh", "r", encoding="utf-8").read()
funcs = re.findall(r"^(load_model_catalog_rows\(\) \{.*?\n\})", content, re.MULTILINE | re.DOTALL)
funcs += re.findall(r"^(get_preset_field\(\) \{.*?\n\})", content, re.MULTILINE | re.DOTALL)
vision = re.search(r"(VISION_CANDIDATES_TSV=\$\(uv run python - <<'\''PY'\''\n.*?\nPY\n\))", content, re.DOTALL)
with open("tmp_funcs.sh", "w", encoding="utf-8", newline="\n") as f:
    for func in funcs:
        f.write(func + "\n\n")
    if vision:
        f.write("get_vision_candidates() {\n")
        f.write(vision.group(1) + "\n")
        f.write("  echo \"$VISION_CANDIDATES_TSV\"\n")
        f.write("}\n")
'

source tmp_funcs.sh

echo "Loading model catalog rows..."
load_model_catalog_rows

echo "Testing ollama_local preset..."
test "$(get_preset_field ollama_local provider)" = "ollama"
test "$(get_preset_field ollama_local model)" = ""
test "$(get_preset_field ollama_local max_tokens)" = "8192"
test "$(get_preset_field ollama_local max_context_tokens)" = "16384"
test "$(get_preset_field ollama_local api_key_env_var)" = ""
test "$(get_preset_field ollama_local api_base)" = "http://localhost:11434"

echo "Testing vision fallback parsing..."
# Extract the vision fallback generation logic from quickstart.sh
export OPENROUTER_API_KEY="dummy"
VISION_CANDIDATES_TSV="$(get_vision_candidates)"

OPENROUTER_LINE=$(echo "$VISION_CANDIDATES_TSV" | grep "^openrouter" | head -n 1)
IFS=$'\x1f' read -r vf_provider vf_model vf_env vf_display <<< "$OPENROUTER_LINE"
test "$vf_provider" = "openrouter"
test -n "$vf_model"
test "$vf_env" = "OPENROUTER_API_KEY"
test "$vf_display" = "openrouter/$vf_model"

echo "All parsing tests passed successfully."
rm -f tmp_funcs.sh
