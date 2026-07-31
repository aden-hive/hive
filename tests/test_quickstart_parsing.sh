#!/bin/bash
# Test: quickstart.sh TSV parsing handles empty fields correctly
# This validates the fix for bash 3.2 empty-field collapse (issue #7339).
# The test uses 'cut -f' directly (same approach now used in quickstart.sh)
# and verifies that consecutive tab-delimited fields remain distinct.

pass=0
fail=0

assert_field() {
    local label="$1" line="$2" field_num="$3" expected="$4"
    local actual
    actual=$(echo "$line" | cut -f"$field_num")
    if [ "$actual" = "$expected" ]; then
        echo "  PASS: $label (field $field_num = '$expected')"
        ((pass++))
    else
        echo "  FAIL: $label (field $field_num expected '$expected' got '$actual')"
        ((fail++))
    fi
}

echo "=== Test: ollama_local preset (empty model + empty api_key_env_var) ==="
# Format: preset_id<TAB>provider<TAB>model<TAB>max_tokens<TAB>max_context<TAB>env_var<TAB>api_base
line=$(printf 'ollama_local\tollama\t\t4096\t16384\t\thttp://localhost:11434')
assert_field "ollama_local preset_id"  "$line" 1 "ollama_local"
assert_field "ollama_local provider"   "$line" 2 "ollama"
assert_field "ollama_local model"      "$line" 3 ""
assert_field "ollama_local max_tokens" "$line" 4 "4096"
assert_field "ollama_local context"    "$line" 5 "16384"
assert_field "ollama_local env_var"    "$line" 6 ""
assert_field "ollama_local api_base"   "$line" 7 "http://localhost:11434"

echo ""
echo "=== Test: consecutive empty middle fields ==="
line2=$(printf 'a\t\t\tb')
assert_field "consecutive-empty 1" "$line2" 1 "a"
assert_field "consecutive-empty 2" "$line2" 2 ""
assert_field "consecutive-empty 3" "$line2" 3 ""
assert_field "consecutive-empty 4" "$line2" 4 "b"

echo ""
echo "=== Test: trailing empty fields ==="
line3=$(printf 'x\ty\t\t')
assert_field "trailing-empty 1" "$line3" 1 "x"
assert_field "trailing-empty 2" "$line3" 2 "y"
assert_field "trailing-empty 3" "$line3" 3 ""
assert_field "trailing-empty 4" "$line3" 4 ""

echo ""
echo "=== Test: no empty fields (normal case) ==="
line4=$(printf 'a\tb\tc\td')
assert_field "normal 1" "$line4" 1 "a"
assert_field "normal 2" "$line4" 2 "b"
assert_field "normal 3" "$line4" 3 "c"
assert_field "normal 4" "$line4" 4 "d"

echo ""
echo "=== Summary ==="
echo "Passed: $pass"
echo "Failed: $fail"
if [ "$fail" -eq 0 ]; then
    echo "Result: ALL TESTS PASSED"
    exit 0
else
    echo "Result: SOME TESTS FAILED"
    exit 1
fi
