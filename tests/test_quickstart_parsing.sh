#!/usr/bin/env bash
# Regression test for the quickstart.sh model-catalogue parsing layer.
#
# Guards the empty-field bug: rows are packed with a single-character field
# separator and read back with `IFS=... read -r a b c ...`. When that separator
# is a tab, bash treats it as IFS whitespace, collapses runs of it into one
# delimiter, and shifts every later field left. The ollama_local preset has two
# empty columns (model, api_key_env_var), so its row lost two positions and
# apply_preset assigned the api_base to SELECTED_MAX_TOKENS, which the config
# writer then fed to int() and crashed on.
#
# The bug reproduces on every bash, not only 3.2 — macOS just hits it first
# because ollama_local is the preset most likely to be picked there.
#
# Runs the real functions out of quickstart.sh, so it fails if either the
# loader (parse_catalog_rows) or the reader (get_preset_field) regresses.

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUICKSTART="$SCRIPT_DIR/../quickstart.sh"

if [ ! -f "$QUICKSTART" ]; then
    echo "FATAL: cannot find quickstart.sh at $QUICKSTART" >&2
    exit 1
fi

# Pull in only the catalogue layer. Sourcing the whole installer would run it.
CATALOG_SRC="$(sed -n '/^CATALOG_FS=/,/^apply_preset() {/p' "$QUICKSTART" | sed '$d')"
if [ -z "$CATALOG_SRC" ]; then
    echo "FATAL: could not extract the catalogue region from quickstart.sh" >&2
    echo "       (expected a CATALOG_FS= line above apply_preset())" >&2
    exit 1
fi
eval "$CATALOG_SRC"

for fn in parse_catalog_rows get_preset_field get_default_model; do
    if ! declare -f "$fn" >/dev/null; then
        echo "FATAL: $fn was not defined by the extracted region" >&2
        exit 1
    fi
done

FAILURES=0
CHECKS=0

check() {
    local label="$1" expected="$2" actual="$3"
    CHECKS=$((CHECKS + 1))
    if [ "$expected" = "$actual" ]; then
        printf '  ok   %s\n' "$label"
    else
        printf '  FAIL %s\n       expected: [%s]\n       actual:   [%s]\n' "$label" "$expected" "$actual"
        FAILURES=$((FAILURES + 1))
    fi
}

# Fixture mirrors what the Python emitter produces, including the two empty
# columns on ollama_local and the empty api_base on a cloud preset.
FS="$CATALOG_FS"
FIXTURE="DEFAULT${FS}anthropic${FS}claude-sonnet-4
DEFAULT${FS}ollama${FS}llama3.1
MODEL${FS}anthropic${FS}claude-sonnet-4${FS}Claude Sonnet 4${FS}8192${FS}200000
PRESET${FS}anthropic${FS}anthropic${FS}claude-sonnet-4${FS}8192${FS}200000${FS}ANTHROPIC_API_KEY${FS}
PRESET${FS}ollama_local${FS}ollama${FS}${FS}4096${FS}8192${FS}${FS}http://localhost:11434
PRESET${FS}ollama_cloud${FS}ollama${FS}${FS}4096${FS}8192${FS}OLLAMA_API_KEY${FS}https://ollama.com
PRESET_MODEL${FS}ollama_local${FS}llama3.1${FS}Llama 3.1${FS}true"

parse_catalog_rows "$FIXTURE"

echo "ollama_local — the preset with two empty columns:"
check "provider"           "ollama"                  "$(get_preset_field ollama_local provider)"
check "model is empty"     ""                        "$(get_preset_field ollama_local model)"
check "max_tokens"         "4096"                    "$(get_preset_field ollama_local max_tokens)"
check "max_context_tokens" "8192"                    "$(get_preset_field ollama_local max_context_tokens)"
check "api_key_env_var empty" ""                     "$(get_preset_field ollama_local api_key_env_var)"
check "api_base"           "http://localhost:11434"  "$(get_preset_field ollama_local api_base)"

echo "ollama_cloud — empty model, populated env var:"
check "model is empty"     ""                        "$(get_preset_field ollama_cloud model)"
check "max_tokens"         "4096"                    "$(get_preset_field ollama_cloud max_tokens)"
check "api_key_env_var"    "OLLAMA_API_KEY"          "$(get_preset_field ollama_cloud api_key_env_var)"
check "api_base"           "https://ollama.com"      "$(get_preset_field ollama_cloud api_base)"

echo "anthropic — every column populated except a trailing empty api_base:"
check "provider"           "anthropic"               "$(get_preset_field anthropic provider)"
check "model"              "claude-sonnet-4"         "$(get_preset_field anthropic model)"
check "max_tokens"         "8192"                    "$(get_preset_field anthropic max_tokens)"
check "api_key_env_var"    "ANTHROPIC_API_KEY"       "$(get_preset_field anthropic api_key_env_var)"
check "trailing api_base empty" ""                   "$(get_preset_field anthropic api_base)"

echo "other row types still parse:"
check "default model"      "claude-sonnet-4"         "$(get_default_model anthropic)"
check "default model 2"    "llama3.1"                "$(get_default_model ollama)"

# The reported crash: the config writer casts both token counts with int().
# Check each one, because a collapsed row can leave the first still numeric
# while the shift has already pushed a URL into the second.
echo "the reported crash path — both int() casts:"
for field in max_tokens max_context_tokens; do
    value="$(get_preset_field ollama_local "$field")"
    CHECKS=$((CHECKS + 1))
    case "$value" in
        ''|*[!0-9]*)
            printf '  FAIL %s would crash int(): [%s]\n' "$field" "$value"
            FAILURES=$((FAILURES + 1))
            ;;
        *)
            printf '  ok   %s survives int()\n' "$field"
            ;;
    esac
done

# api_base must still look like a URL rather than have been shifted away.
CHECKS=$((CHECKS + 1))
base="$(get_preset_field ollama_local api_base)"
case "$base" in
    http://*|https://*)
        printf '  ok   api_base kept its value\n'
        ;;
    *)
        printf '  FAIL api_base was shifted out of position: [%s]\n' "$base"
        FAILURES=$((FAILURES + 1))
        ;;
esac

echo ""
if [ "$FAILURES" -ne 0 ]; then
    echo "$FAILURES of $CHECKS checks failed"
    exit 1
fi
echo "all $CHECKS checks passed"
